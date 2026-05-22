# -*- coding: utf-8 -*-

# Save to GIF converter module for Hikka & Friendly-Telegram Userbots
# Developed by Antigravity
# requires: imageio-ffmpeg

import os
import asyncio
import tempfile
import shutil
from PIL import Image, ImageColor
from telethon.tl.types import DocumentAttributeAnimated, DocumentAttributeFilename
from .. import loader, utils

@loader.tds
class ImageToGifMod(loader.Module):
    """Converts images, photos, and stickers into saveable Telegram GIFs"""

    strings = {
        "name": "ImageToGif",
        "loading": "⚡️ <b>Converting image to GIF...</b>",
        "loading_pillow": "⚡️ <b>FFmpeg not found. Using Pillow fallback (quality may be lower)...</b>",
        "no_reply": "⚠️ <b>Please reply to an image, photo, or sticker, or use .togif as a caption!</b>",
        "not_an_image": "❌ <b>The replied file is not a supported image format!</b>",
        "error": "❌ <b>An error occurred during conversion:</b> {}",
        "done": "✅ <b>Successfully converted!</b>",
        "_cmd_doc_togif": "Convert a replied image/sticker or captioned image to a saveable GIF",
    }

    strings_ru = {
        "loading": "⚡️ <b>Конвертирую изображение в GIF...</b>",
        "loading_pillow": "⚡️ <b>FFmpeg не найден. Использую Pillow (качество может быть ниже)...</b>",
        "no_reply": "⚠️ <b>Пожалуйста, ответьте на изображение, фото или стикер, либо укажите .togif в качестве подписи!</b>",
        "not_an_image": "❌ <b>Файл не поддерживается или не является изображением!</b>",
        "error": "❌ <b>Произошла ошибка при конвертации:</b> {}",
        "done": "✅ <b>Успешно конвертировано!</b>",
        "_cmd_doc_togif": "Конвертировать изображение/стикер в сохраняемую гифку (ответ на медиа или подпись)",
    }


    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "bg_color",
                "#000000",
                lambda: "Background color for transparent images (HEX or name)",
            ),
            loader.ConfigValue(
                "duration",
                3.0,
                lambda: "Duration of the output GIF in seconds (for FFmpeg engine)",
            ),
            loader.ConfigValue(
                "gif_delay",
                10,
                lambda: "Delay for each frame in milliseconds for the GIF (default 10)",
            ),
            loader.ConfigValue(
                "max_size",
                800,
                lambda: "Maximum width/height of the GIF (0 to disable resizing)",
            ),
            loader.ConfigValue(
                "dither",
                True,
                lambda: "Use Floyd-Steinberg dithering for Pillow fallback (True/False)",
            ),
        )

    async def client_ready(self, client, db):
        self.client = client

    async def togifcmd(self, message):
        """Reply to an image/sticker or use as caption to convert it to a saveable GIF"""
        reply = await message.get_reply_message()

        # Check if the command itself has media (caption) or reply has media
        target_msg = None
        if message.media:
            target_msg = message
        elif reply and reply.media:
            target_msg = reply

        if not target_msg:
            await utils.answer(message, self.strings("no_reply"))
            return

        # Show conversion status
        message = await utils.answer(message, self.strings("loading"))

        # Download media file
        path = await self.client.download_media(target_msg)
        if not path:
            await utils.answer(message, self.strings("no_reply"))
            return

        # Verify and open image
        try:
            img = Image.open(path)
        except Exception:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
            await utils.answer(message, self.strings("not_an_image"))
            return

        # Handle transparency (blend with configured background color)
        try:
            if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                bg_color = self.config["bg_color"]
                try:
                    bg_rgb = ImageColor.getrgb(bg_color)
                except Exception:
                    bg_rgb = (0, 0, 0)  # Default fallback to black

                if img.mode == 'LA':
                    img = img.convert('RGBA')
                elif img.mode == 'P':
                    img = img.convert('RGBA')

                # Create background image and paste original on top
                bg = Image.new("RGBA", img.size, bg_rgb + (255,))
                bg.paste(img, (0, 0), img)
                img = bg.convert('RGB')
            else:
                img = img.convert('RGB')
        except Exception as e:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
            await utils.answer(message, self.strings("error").format(str(e)))
            return

        out_path = path + ".gif"
        use_ffmpeg = False

        # Parse configurations
        try:
            max_size = int(self.config["max_size"])
        except Exception:
            max_size = 800

        try:
            gif_delay = int(self.config["gif_delay"])
        except Exception:
            gif_delay = 10

        try:
            use_dither = self.config["dither"]
            if isinstance(use_dither, str):
                use_dither = use_dither.lower() in ('true', 'yes', '1')
        except Exception:
            use_dither = True

        try:
            duration = float(self.config["duration"])
        except Exception:
            duration = 3.0

        # Centralized resize logic:
        # If max_size > 0, resize to max_size.
        # If max_size == 0, cap at 1920 to prevent encoding/transcoding issues.
        limit_size = max_size if max_size > 0 else 1920
        w, h = img.size
        if max(w, h) > limit_size:
            try:
                resample_filter = Image.Resampling.LANCZOS
            except AttributeError:
                try:
                    resample_filter = Image.LANCZOS
                except AttributeError:
                    resample_filter = Image.ANTIALIAS
            img.thumbnail((limit_size, limit_size), resample_filter)

        # 1. Try to convert using FFmpeg (creates a high-quality, lightweight MP4)
        ffmpeg_bin = 'ffmpeg'
        try:
            import imageio_ffmpeg
            ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass

        try:
            # Check if ffmpeg works
            process = await asyncio.create_subprocess_exec(
                ffmpeg_bin, '-version',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            if process.returncode == 0:
                use_ffmpeg = True
        except Exception:
            use_ffmpeg = False

        if use_ffmpeg:
            try:
                w, h = img.size

                # Create a temporary directory to save the two frames
                temp_dir = tempfile.mkdtemp()
                try:
                    frame1_path = os.path.join(temp_dir, "1.png")
                    frame2_path = os.path.join(temp_dir, "2.png")

                    # Frame 1: original image
                    img.save(frame1_path, "PNG")

                    # Frame 2: original image with a 1-pixel color shift
                    img2 = img.copy()
                    orig_pixel = img.getpixel((0, 0))
                    if isinstance(orig_pixel, tuple):
                        new_pixel = tuple((val + 1) % 256 for val in orig_pixel)
                    else:
                        new_pixel = (orig_pixel + 1) % 256
                    img2.putpixel((0, 0), new_pixel)
                    img2.save(frame2_path, "PNG")

                    dither_val = 'floyd_steinberg' if use_dither else 'none'
                    framerate_val = 1000.0 / max(1, gif_delay)

                    # Generate looping GIF from the two frames
                    cmd = [
                        ffmpeg_bin, '-y',
                        '-framerate', str(framerate_val),
                        '-i', os.path.join(temp_dir, "%d.png"),
                        '-vf', f'scale={w}:{h}:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=single[p];[s1][p]paletteuse=dither={dither_val}',
                        '-loop', '0',
                        out_path
                    ]

                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await process.communicate()

                    if process.returncode != 0 or not os.path.exists(out_path):
                        use_ffmpeg = False
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                use_ffmpeg = False

        # 2. Fall back to Pillow (creates a looping GIF)
        if not use_ffmpeg:
            try:
                out_path = path + ".gif"
                # Update status to warn user that Pillow fallback is used
                message = await utils.answer(message, self.strings("loading_pillow"))

                # Determine dither mode
                if use_dither:
                    try:
                        dither_val = Image.Dither.FLOYDSTEINBERG
                    except AttributeError:
                        dither_val = 1
                else:
                    try:
                        dither_val = Image.Dither.NONE
                    except AttributeError:
                        dither_val = 0

                # Convert to P (Palette) mode first, then modify pixel index of a single pixel.
                # This prevents Pillow's GIF encoder from merging frames if RGB values quantize
                # to the same palette index in real, multi-color images.
                img_p1 = img.convert('P', palette=Image.ADAPTIVE, dither=dither_val)
                img_p2 = img_p1.copy()
                orig_index = img_p2.getpixel((0, 0))
                new_index = 0 if orig_index != 0 else 1
                img_p2.putpixel((0, 0), new_index)

                img_p1.save(
                    out_path,
                    format="GIF",
                    save_all=True,
                    append_images=[img_p2],
                    duration=gif_delay,
                    loop=0,
                    disposal=2,
                    optimize=False
                )
            except Exception as e:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                await utils.answer(message, self.strings("error").format(str(e)))
                return

        # Send resulting file with appropriate attributes to enable "Save to GIFs"
        try:
            # Determine if we should reply to the original message
            reply_to = None
            if target_msg != message:
                reply_to = target_msg.id

            file_name = os.path.basename(out_path)
            attrs = [
                DocumentAttributeAnimated(),
                DocumentAttributeFilename(file_name=file_name)
            ]

            await self.client.send_file(
                message.chat_id,
                out_path,
                reply_to=reply_to,
                attributes=attrs
            )

            # Delete the trigger command message
            await message.delete()
        except Exception as e:
            await utils.answer(message, self.strings("error").format(str(e)))
        finally:
            # Clean up all residual files
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
            if out_path and os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except Exception:
                    pass

