from ultralytics import YOLO

print("Loading YOLO-World...")
model = YOLO("yolov8s-world.pt")
print("Setting classes...")
model.set_classes(["person", "door", "obstacle"])
print("Classes set:", model.names)
print("Done!")
