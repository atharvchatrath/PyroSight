import cv2
import numpy as np
from ultralytics import YOLO
import random

# Configuration
YOLO_MODEL = 'yolov8s-world.pt'

# Distance Calibration
FOCAL_LENGTH = 800
PERSON_HEIGHT_INCHES = 66
DOOR_HEIGHT_INCHES = 80

# HSV color range for bright orange/yellow (Fire simulation)
LOWER_FIRE = np.array([10, 150, 150])
UPPER_FIRE = np.array([40, 255, 255])

def get_distance(real_height_inches, bbox_height_pixels):
    if bbox_height_pixels == 0:
        return -1
    distance_ft = (real_height_inches * FOCAL_LENGTH) / bbox_height_pixels / 12
    return distance_ft

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
    model.set_classes(["person", "door", "doorway", "exit"])
    
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
        # Force threshold to 0.15 to catch partial doors
        results = model(frame, conf=0.15, verbose=False)
        
        doors_detected = []
        persons_detected = []
        
        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0])
                cls_name = model.names[cls_id].lower() if model.names else ""
                
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                bbox_height_pixels = y2 - y1
                
                if cls_name == 'person':
                    dist = get_distance(PERSON_HEIGHT_INCHES, bbox_height_pixels)
                    persons_detected.append({'box': (x1, y1, x2, y2), 'dist': dist})
                elif cls_name in ['door', 'doorway', 'exit']:
                    dist = get_distance(DOOR_HEIGHT_INCHES, bbox_height_pixels)
                    doors_detected.append({'box': (x1, y1, x2, y2), 'dist': dist})

        # 2. Fire Hazard Simulation
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, LOWER_FIRE, UPPER_FIRE)
        kernel = np.ones((5,5), np.uint8)
        mask = cv2.erode(mask, kernel, iterations=1)
        mask = cv2.dilate(mask, kernel, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        fire_hazards = []
        for cnt in contours:
            if cv2.contourArea(cnt) > 2000:
                x, y, w, h = cv2.boundingRect(cnt)
                # Cast to int for safety
                fire_hazards.append((int(x), int(y), int(w), int(h)))

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
        for d in doors_detected:
            x1, y1, x2, y2 = d['box']
            draw_hud_box(frame, x1, y1, x2, y2, (0, 255, 0), "EXIT DOOR", distance=d['dist'])
            
            # Start exactly at bottom center of screen
            start_pt = (int(w_frame / 2), int(h_frame))
            # End at bottom center of door
            end_pt = (int((x1 + x2) / 2), int(y2))
            
            # Obstacle Avoidance logic
            path_points = [start_pt, end_pt]
            
            for (hx, hy, hw, hh) in fire_hazards:
                if line_intersects_rect(start_pt, end_pt, (hx, hy, hw, hh)):
                    hazard_cx = hx + hw // 2
                    shift_amount = hw + 100
                    # Shift left or right
                    if (start_pt[0] + end_pt[0]) // 2 < hazard_cx:
                        mid_x = hazard_cx - shift_amount
                    else:
                        mid_x = hazard_cx + shift_amount
                    mid_y = int(hy + hh / 2) # mid point in y
                    
                    mid_pt = (int(mid_x), int(mid_y))
                    path_points = [start_pt, mid_pt, end_pt]
                    break 

            # Draw the path
            for i in range(len(path_points) - 1):
                pt1 = path_points[i]
                pt2 = path_points[i+1]
                cv2.line(overlay, pt1, pt2, (0, 255, 0), 8)
                cv2.line(overlay, pt1, pt2, (150, 255, 150), 3)

        alpha = 0.6
        frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)

        cv2.putText(frame, "PyroSight v3.0", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 0), 2)
        cv2.putText(frame, "MODE: ROBUST ROUTING", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        
        cv2.imshow("PyroSight Prototype", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
