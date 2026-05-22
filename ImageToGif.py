# -*- coding: utf-8 -*-

# Save to GIF converter module for Hikka & Friendly-Telegram Userbots
# Developed by Antigravity

import os
import asyncio
from PIL import Image, ImageColor
from telethon.tl.types import DocumentAttributeAnimated, DocumentAttributeFilename
from .. import loader, utils

@loader.tds
class ImageToGifMod(loader.Module):
    """Converts images, photos, and stickers into saveable Telegram GIFs"""

    strings = {
        "name": "ImageToGif",
        "loading": "⚡️ <b>Converting image to GIF...</b>",
        "no_reply": "⚠️ <b>Please reply to an image, photo, or sticker, or use .togif as a caption!</b>",
        "not_an_image": "❌ <b>The replied file is not a supported image format!</b>",
        "error": "❌ <b>An error occurred during conversion:</b> {}",
        "done": "✅ <b>Successfully converted!</b>",
        "_cmd_doc_togif": "Convert a replied image/sticker or captioned image to a saveable GIF",
    }

    strings_ru = {
        "loading": "⚡️ <b>Конвертирую изображение в GIF...</b>",
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
        temp_mp4 = path + "_temp.mp4"
        temp_img = path + "_proc.png"

        # 1. Try to convert using FFmpeg (creates a high-quality, lightweight MP4)
        try:
            duration = float(self.config["duration"])
            w, h = img.size
            w_even = max(2, (w // 2) * 2)
            h_even = max(2, (h // 2) * 2)

            img.save(temp_img, "PNG")

            cmd = [
                'ffmpeg', '-y',
                '-loop', '1',
                '-framerate', '10',
                '-i', temp_img,
                '-c:v', 'libx264',
                '-t', str(duration),
                '-pix_fmt', 'yuv420p',
                '-vf', f'scale={w_even}:{h_even}',
                '-an',
                temp_mp4
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()

            if process.returncode == 0 and os.path.exists(temp_mp4):
                # Rename to .gif extension so Telethon uploads it as a document (GIF)
                # rather than a standard video with seek bars.
                if os.path.exists(out_path):
                    os.remove(out_path)
                os.rename(temp_mp4, out_path)
                use_ffmpeg = True
        except Exception:
            use_ffmpeg = False
        finally:
            if os.path.exists(temp_img):
                try:
                    os.remove(temp_img)
                except Exception:
                    pass
            if os.path.exists(temp_mp4):
                try:
                    os.remove(temp_mp4)
                except Exception:
                    pass

        # 2. Fall back to Pillow (creates a looping GIF)
        if not use_ffmpeg:
            try:
                # Get configuration values
                try:
                    gif_delay = int(self.config["gif_delay"])
                except Exception:
                    gif_delay = 10

                try:
                    max_size = int(self.config["max_size"])
                except Exception:
                    max_size = 800

                try:
                    use_dither = self.config["dither"]
                    if isinstance(use_dither, str):
                        use_dither = use_dither.lower() in ('true', 'yes', '1')
                except Exception:
                    use_dither = True

                # Resize image using high-quality resampler before quantization if it's too large
                if max_size > 0:
                    w, h = img.size
                    if max(w, h) > max_size:
                        try:
                            resample_filter = Image.Resampling.LANCZOS
                        except AttributeError:
                            try:
                                resample_filter = Image.LANCZOS
                            except AttributeError:
                                resample_filter = Image.ANTIALIAS
                        img.thumbnail((max_size, max_size), resample_filter)

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

                # Save as 2-frame looping GIF matching the ezgif settings:
                # - 2 frames (duplicated static image with slight pixel index variation)
                # - delay: gif_delay ms (duration=gif_delay)
                # - loop: loop forever (loop=0)
                # - disposal: restore to background (disposal=2)
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
            if not file_name.lower().endswith('.gif'):
                file_name = os.path.splitext(file_name)[0] + '.gif'

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

