"""Mouth-only lossless transport for native QinChe; legacy JPEG for Gentleman."""
import cv2
import numpy as np

def frame_metadata(engine,index,native):
    result={'type':'frame','index':index,'format':'full_jpeg'}
    if native:
        result.update(format='mouth_png',bbox=engine.bboxes[index].tolist(),
                      canvas=[engine.manifest['width'],engine.manifest['height']])
    return result

def encode_frame(engine,index,image,native):
    if native:
        source=int(engine.source_indices[index])
        x1,y1,x2,y2=map(int,engine.bboxes[index])
        patch=cv2.cvtColor(image[y1:y2,x1:x2],cv2.COLOR_BGR2BGRA)
        # RGB has already been feathered by NativeFaceMatch; do not blend it twice.
        patch[:,:,3]=np.where(engine.prepared[source]['alpha'][:,:,0]>0,255,0).astype(np.uint8)
        ok,data=cv2.imencode('.png',patch,[cv2.IMWRITE_PNG_COMPRESSION,1])
    else:
        ok,data=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,95])
    if not ok:raise RuntimeError('Avatar frame encoding failed')
    return data.tobytes()
