"""
fix_known_faces.py
--------------------
Run this ONCE from your project root (needs Pillow: pip install Pillow).
Forces every image in known_faces/ into true 8-bit RGB JPEG -- fixes
"Unsupported image type, must be 8bit gray or RGB image" from
face_recognition/dlib. The earlier cv2 round-trip didn't fix this because
face_recognition uses a different image loader (PIL/imageio) than cv2 --
this script uses the SAME loader path that was actually failing.

USAGE:
  python fix_known_faces.py
"""

from PIL import Image
import os

KNOWN_FACES_DIR = "known_faces"

def main():
    if not os.path.exists(KNOWN_FACES_DIR):
        print(f"'{KNOWN_FACES_DIR}' folder not found. Run this from your project root.")
        return

    fixed = 0
    for filename in os.listdir(KNOWN_FACES_DIR):
        if not filename.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        path = os.path.join(KNOWN_FACES_DIR, filename)
        try:
            img = Image.open(path)
            # .convert("RGB") strips alpha channels, CMYK profiles, palette
            # modes, 16-bit depth -- everything that trips up dlib.
            rgb_img = img.convert("RGB")
            rgb_img.save(path, "JPEG", quality=95)
            print(f"Fixed: {filename}")
            fixed += 1
        except Exception as e:
            print(f"FAILED on {filename}: {e}")

    print(f"\nDone. {fixed} image(s) converted to true 8-bit RGB JPEG.")
    print("Restart your server -- face profiles should load without errors now.")

if __name__ == "__main__":
    main()
