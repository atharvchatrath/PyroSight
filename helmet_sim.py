import cv2
import numpy as np
from ultralytics import YOLO
import random
import math

# Configuration
YOLO_MODEL = 'yolov8s-world.pt'

# Distance Calibration
FOCAL_LENGTH = 800
PERSON_HEIGHT_INCHES = 66
DOOR_HEIGHT_INCHES = 80

def get_distance(real_height_inches, bbox_height_pixels):
    if bbox_height_pixels == 0:
        return -1
    distance_ft = (real_height_inches * FOCAL_LENGTH) / bbox_height_pixels / 12
    return distance_ft

def bezier_curve(p0, p1, p2, num_points=50):
    points = []
    for t in np.linspace(0, 1, num_points):
        x = int((1 - t)**2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0])
        y = int((1 - t)**2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1])
        points.append((x, y))
    return points

def draw_chevrons_on_curve(img, curve_points, color=(0, 255, 0), chevron_count=12):
    if len(curve_points) < 2: return
    
    step = len(curve_points) // chevron_count
    if step == 0: step = 1
    
    # Draw the underlying curve lightly
    pts = np.array(curve_points, np.int32).reshape((-1, 1, 2))
    cv2.polylines(img, [pts], isClosed=False, color=(0, 50, 0), thickness=8)
    
    for i in range(0, len(curve_points) - 1, step):
        pt1 = curve_points[i]
        pt2 = curve_points[min(i + 3, len(curve_points)-1)]
        
        dx = pt2[0] - pt1[0]
        dy = pt2[1] - pt1[1]
        theta = math.atan2(dy, dx)
        
        y_val = pt1[1]
        size = int(max(10, y_val / 18)) 
        
        alpha = math.pi / 4 # 45 degree spread
        
        tip = (pt1[0] + int(math.cos(theta) * size), pt1[1] + int(math.sin(theta) * size))
        
        l_angle = theta - alpha + math.pi
        left_pt = (tip[0] + int(math.cos(l_angle) * size * 1.5), tip[1] + int(math.sin(l_angle) * size * 1.5))
        
        r_angle = theta + alpha + math.pi
        right_pt = (tip[0] + int(math.cos(r_angle) * size * 1.5), tip[1] + int(math.sin(r_angle) * size * 1.5))
        
        c_pts = np.array([left_pt, tip, right_pt], np.int32).reshape((-1, 1, 2))
        
        # Black outline
        cv2.polylines(img, [c_pts], isClosed=False, color=(0, 0, 0), thickness=size//2 + 4)
        # Inner glow
        cv2.polylines(img, [c_pts], isClosed=False, color=(150, 255, 150), thickness=size//2)
        cv2.polylines(img, [c_pts], isClosed=False, color=color, thickness=size//2 - 2)

def draw_hud_box(img, x1, y1, x2, y2, color, label, thickness=2, distance=None):
    # CRITICAL: Fix OpenCV float crash by casting to integers
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    line_len = int(min(x2-x1, y2-y1) * 0.2)
    
    cv2.line(img, (x1, y1), (x1 + line_len, y1), color, thickness)
    cv2.line(img, (x1, y1), (x1, y1 + line_len), color, thickness)
    cv2.line(img, (x2, y1), (x2 - line_len, y1), color, thickness)
    cv2.line(img, (x2, y1), (x2, y1 + line_len), color, thickness)
    cv2.line(img, (x1, y2), (x1 + line_len, y2), color, thickness)
    cv2.line(img, (x1, y2), (x1, y2 - line_len), color, thickness)
    cv2.line(img, (x2, y2), (x2 - line_len, y2), color, thickness)
    cv2.line(img, (x2, y2), (x2, y2 - line_len), color, thickness)

    (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.rectangle(img, (x1, y1 - text_h - 10), (x1 + text_w + 10, y1), color, -1)
    cv2.putText(img, label, (x1 + 5, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    
    if distance is not None and distance >= 0:
        dist_str = f"{distance:.1f} ft"
        (d_w, d_h), _ = cv2.getTextSize(dist_str, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(img, (x2 - d_w - 10, y1 - d_h - 10), (x2, y1), color, -1)
        cv2.putText(img, dist_str, (x2 - d_w - 5, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

def line_intersects_rect(p1, p2, rect):
    rx, ry, rw, rh = rect
    min_x = min(p1[0], p2[0])
    max_x = max(p1[0], p2[0])
    min_y = min(p1[1], p2[1])
    max_y = max(p1[1], p2[1])
    if (min_x < rx + rw and max_x > rx and min_y < ry + rh and max_y > ry):
        return True
    return False

def main():
    print("[INIT] Loading YOLOv8-World Model...", flush=True)
    model = YOLO(YOLO_MODEL)
    print("[INIT] Setting custom AI vocabulary for robust detection...", flush=True)
    model.set_classes(["person", "door", "doorway", "exit", "fire", "flame"])
    
    print("[INIT] Opening Webcam... (Trying index 0)", flush=True)
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("Error: Could not open webcam at index 0.", flush=True)
        return

    print("[INIT] Webcam opened successfully. Waiting for first frame...", flush=True)
    
    current_temp = 600
    frame_count = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Error: Could not read frame from webcam.", flush=True)
            break
            
        frame_count += 1
        if frame_count == 1:
            print("[SUCCESS] First frame captured! Launching the video window now...", flush=True)
            
        frame = cv2.flip(frame, 1)
        h_frame, w_frame, _ = frame.shape
        overlay = frame.copy()
        
        # 1. AI Object Detection
        # Increased threshold significantly to 0.35 to prevent hallucinating bookshelves/shirts
        results = model(frame, conf=0.35, verbose=False)
        
        doors_detected = []
        persons_detected = []
        fire_hazards = []
        
        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0])
                cls_name = model.names[cls_id].lower() if model.names else ""
                
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                bbox_height_pixels = y2 - y1
                
                if cls_name == 'person':
                    dist = get_distance(PERSON_HEIGHT_INCHES, bbox_height_pixels)
                    persons_detected.append({'box': (x1, y1, x2, y2), 'dist': dist})
                elif cls_name in ["door", "doorway", "exit"]:
                    dist = get_distance(DOOR_HEIGHT_INCHES, bbox_height_pixels)
                    doors_detected.append({'box': (x1, y1, x2, y2), 'dist': dist})
                elif cls_name in ["fire", "flame"]:
                    w = x2 - x1
                    h = y2 - y1
                    fire_hazards.append((int(x1), int(y1), int(w), int(h)))

        # 2. Fire Hazard Simulation (Temperature only now, detection is AI-based)
        if fire_hazards:
            current_temp = min(1100, current_temp + random.randint(10, 50))
        else:
            current_temp = max(600, current_temp - random.randint(10, 30))

        # 3. Draw Hazards
        for (x, y, w, h) in fire_hazards:
            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 0, 255), 4)
            label = f"HAZARD - BLOCKED ({current_temp} F)"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            cv2.rectangle(frame, (x, y-th-10), (x+tw+10, y), (0, 0, 255), -1)
            cv2.putText(frame, label, (x+5, y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # 4. Draw Persons
        for p in persons_detected:
            x1, y1, x2, y2 = p['box']
            draw_hud_box(frame, x1, y1, x2, y2, (255, 255, 0), "PERSON", distance=p['dist'])

        # 5. Draw Doors & AR Navigation Route
        # Lock onto ONLY the largest door to prevent sensor confusion
        if doors_detected:
            doors_detected.sort(key=lambda d: (d['box'][2] - d['box'][0]) * (d['box'][3] - d['box'][1]), reverse=True)
            d = doors_detected[0] # Target locked
            
            x1, y1, x2, y2 = d['box']
            draw_hud_box(frame, x1, y1, x2, y2, (0, 255, 0), "EXIT LOCKED", distance=d['dist'])
            
            # Start exactly at bottom center of screen
            start_pt = (int(w_frame / 2), int(h_frame))
            # End at bottom center of door
            end_pt = (int((x1 + x2) / 2), int(y2))
            
            # Default control point
            ctrl_pt = ((start_pt[0] + end_pt[0]) // 2, (start_pt[1] + end_pt[1]) // 2)
            
            # Obstacle Avoidance logic (Fire)
            for (hx, hy, hw, hh) in fire_hazards:
                if line_intersects_rect(start_pt, end_pt, (hx, hy, hw, hh)):
                    hazard_cx = hx + hw // 2
                    shift_amount = hw + 100
                    if ctrl_pt[0] < hazard_cx:
                        ctrl_pt = (hazard_cx - shift_amount, ctrl_pt[1])
                    else:
                        ctrl_pt = (hazard_cx + shift_amount, ctrl_pt[1])
                    break 

            # Draw the path
            curve = bezier_curve(start_pt, ctrl_pt, end_pt)
            draw_chevrons_on_curve(overlay, curve)

        alpha = 0.6
        frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)

        cv2.putText(frame, "PyroSight v4.0", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 0), 2)
        cv2.putText(frame, "MODE: AI SENSOR LOCK", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        
        cv2.imshow("PyroSight Prototype", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
