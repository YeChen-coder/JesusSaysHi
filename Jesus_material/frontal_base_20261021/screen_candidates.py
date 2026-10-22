"""Measure generated composition with the unchanged FeatherTalk 110-point detector."""
import os,sys,json,hashlib
from pathlib import Path
import cv2,numpy as np,torch
from PIL import Image
torch.set_num_threads(2);cv2.setNumThreads(1)
sys.path.insert(0,'/opt/FeatherTalk');os.chdir('/opt/FeatherTalk/data_utils');sys.path.insert(0,os.getcwd())
from get_landmark import Landmark
from face_utils import compute_face_bbox
root=Path('/out');manifest=json.loads((root/'request_manifest.json').read_text());det=Landmark();rows=[]
with torch.inference_mode():
    for variant in manifest['variants']:
        files=[p for p in root.glob(variant['id']+'.*') if p.suffix.lower() in ['.jpg','.jpeg','.png','.webp']]
        if not files:continue
        assert len(files)==1,files
        file=files[0];image=cv2.imread(str(file));assert image is not None;h,w=image.shape[:2]
        row={'id':variant['id'],'label':variant['label'],'round':variant.get('round',1),'file':file.name,'width':w,'height':h,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
        try:
            pts,x,y=det.detect(str(file));pts=pts+np.array([x,y]);bbox=tuple(map(int,compute_face_bbox(pts)))
            assert pts.shape==(110,2)
            bw=bbox[2]-bbox[0];normalized=bw*720/w
            row.update(bbox_xyxy=bbox,landmark_count=110,native_lower_face_width=bw,lower_face_width_at_720=normalized,target_140_160=140<=normalized<=160,reference_old_width_at_720=399*720/1152)
            x1,y1,x2,y2=bbox
            assert 0<=x1<x2<=w and 0<=y1<y2<=h
            crop=image[y1:y2,x1:x2]
            Image.fromarray(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB)).save(root/(variant['id']+'_face_preview.png'),compress_level=0)
        except Exception as e:row['detection_error']=str(e)
        row['identity_and_anatomy']='manual review required; sizing does not establish likeness'
        rows.append(row)
(root/'screening.json').write_text(json.dumps({'rows':rows,'method':'official compute_face_bbox; normalization to 720px video width, no changes to native generated images'},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(rows,ensure_ascii=False),flush=True)
