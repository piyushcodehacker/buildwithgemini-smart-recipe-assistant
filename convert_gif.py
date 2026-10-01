import imageio
from PIL import Image

def convert():
    print("Reading agent_demo.webm...")
    reader = imageio.get_reader("agent_demo.webm")
    fps = reader.get_meta_data().get("fps", 25)
    
    frames = []
    # Sample 5 fps
    step = max(1, int(fps // 5))
    
    for i, frame in enumerate(reader):
        if i % step == 0:
            img = Image.fromarray(frame)
            w, h = img.size
            new_w = 640
            new_h = int(h * (new_w / w))
            img = img.resize((new_w, new_h), Image.Resampling.BILINEAR)
            # Quantize to 256 colors for fast GIF creation
            frames.append(img.convert("P", palette=Image.Palette.ADAPTIVE, colors=256))

    print(f"Captured {len(frames)} frames. Writing agent_demo.gif...")
    frames[0].save(
        "agent_demo.gif",
        save_all=True,
        append_images=frames[1:],
        duration=200,  # 200ms = 5 fps
        loop=0
    )
    print("GIF conversion complete!")

if __name__ == "__main__":
    convert()
