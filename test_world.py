import cv2
import numpy as np
import math

def bezier_curve(p0, p1, p2, num_points=100):
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
    cv2.polylines(img, [pts], isClosed=False, color=(0, 50, 0), thickness=15)
    
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
        
        pts = np.array([left_pt, tip, right_pt], np.int32).reshape((-1, 1, 2))
        
        # Black outline
        cv2.polylines(img, [pts], isClosed=False, color=(0, 0, 0), thickness=size//2 + 4)
        # Inner glow
        cv2.polylines(img, [pts], isClosed=False, color=(150, 255, 150), thickness=size//2)
        cv2.polylines(img, [pts], isClosed=False, color=color, thickness=size//2 - 2)

img = np.zeros((720, 1280, 3), dtype=np.uint8)
p0 = (640, 720)
p1 = (1000, 400)
p2 = (200, 100)

curve = bezier_curve(p0, p1, p2)
draw_chevrons_on_curve(img, curve, color=(0, 255, 0))

cv2.imwrite("chevron_test.jpg", img)
