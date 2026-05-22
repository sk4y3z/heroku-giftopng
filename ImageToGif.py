# -*- coding: utf-8 -*-

# Save to GIF converter module for Hikka & Friendly-Telegram Userbots
# Developed by Antigravity

import os
import asyncio
from PIL import Image, ImageColor
from telethon.tl.types import DocumentAttributeAnimated, DocumentAttributeVideo, DocumentAttributeFilename
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

        use_ffmpeg = False
        out_path = None

        # 1. Try to convert using FFmpeg (creates a high-quality, lightweight GIF)
        try:
            temp_img = path + "_proc.png"
            img.save(temp_img, "PNG")

            out_path = path + ".gif"
            duration = float(self.config["duration"])

            cmd = [
                'ffmpeg', '-y',
                '-loop', '1',
                '-r', '10',
                '-i', temp_img,
                '-t', str(duration),
                '-vf', 'split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse',
                out_path
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()

            # Cleanup temporary processed image
            if os.path.exists(temp_img):
                os.remove(temp_img)

            if process.returncode == 0:
                use_ffmpeg = True
        except FileNotFoundError:
            # FFmpeg is not installed
            use_ffmpeg = False
        except Exception:
            use_ffmpeg = False

        # 2. Fall back to Pillow (creates a looping GIF)
        if not use_ffmpeg:
            out_path = path + ".gif"
            try:
                # Save as 2-frame looping GIF to satisfy Telegram's animation checks
                img.save(
                    out_path,
                    format="GIF",
                    save_all=True,
                    append_images=[img],
                    duration=500,
                    loop=0
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
