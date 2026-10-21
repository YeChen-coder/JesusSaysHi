"""Local face/lip geometry utilities for the isolated teeth experiment."""
import cv2,numpy as np

INNER=(78,191,80,81,82,13,312,311,310,415,308,324,318,402,317,14,87,178,88,95)

def roi_from_points(points,width,height):
    low=points.min(axis=0);high=points.max(axis=0);span=high-low
    low-=span*np.array([.18,.45]);high+=span*np.array([.18,.12])
    return (max(0,int(low[0])),max(0,int(low[1])),min(width,int(high[0])+1),min(height,int(high[1])+1))

def mesh_points(mesh,image,roi):
    x1,y1,x2,y2=roi;crop=image[y1:y2,x1:x2];h,w=crop.shape[:2]
    scale=min(1.5,320/max(h,w))
    small=cv2.resize(crop,(round(w*scale),round(h*scale)))
    result=mesh.process(cv2.cvtColor(small,cv2.COLOR_BGR2RGB))
    if not result.multi_face_landmarks:return None
    return np.asarray([(p.x*w+x1,p.y*h+y1) for p in result.multi_face_landmarks[0].landmark],np.float32)

def curves(points,xs):
    upper=points[list(INNER[:11])];lower=points[list((INNER[0],)+INNER[10:])]
    upper=upper[np.argsort(upper[:,0])];lower=lower[np.argsort(lower[:,0])]
    return np.interp(xs,upper[:,0],upper[:,1]),np.interp(xs,lower[:,0],lower[:,1])

def jaw_transform(target,source):
    source_axis=source[263]-source[33];target_axis=target[263]-target[33]
    den=float(source_axis@source_axis)
    if den<25:raise ValueError('Degenerate donor geometry')
    a=float(source_axis@target_axis)/den;b=float(source_axis[0]*target_axis[1]-source_axis[1]*target_axis[0])/den
    linear=np.array([[a,-b],[b,a]],np.float32)
    return np.column_stack([linear,target[168]-linear@source[168]]).astype(np.float32)

def mouth_stats(image,points):
    polygon=points[list(INNER)];left,right=float(points[78,0]),float(points[308,0]);width=right-left
    x0,y0=np.maximum(np.floor(polygon.min(axis=0)-2).astype(int),0)
    x1,y1=np.minimum(np.ceil(polygon.max(axis=0)+3).astype(int),image.shape[1::-1])
    if x1<=x0 or y1<=y0 or width<8:return None
    patch=image[y0:y1,x0:x1];mask=np.zeros(patch.shape[:2],np.uint8)
    cv2.fillPoly(mask,[np.rint(polygon-[x0,y0]).astype(np.int32)],255)
    hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
    white=(hsv[:,:,1]<85)&(hsv[:,:,2]>125)&(mask>0)
    tooth_fraction=float(white.sum()/max((mask>0).sum(),1))
    sharpness=float(cv2.Laplacian(cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY),cv2.CV_32F).var())
    gap=max(0,float(points[14,1]-points[13,1]));opening=gap/max(width,1)
    return dict(width=width,gap=gap,opening=opening,tooth_fraction=tooth_fraction,sharpness=sharpness,
                glare_fraction=float(((hsv[:,:,2]>248)&white).sum()/max(white.sum(),1)))
