"""Restore upper dentition from new same-character footage, inside current lips."""
import json,time
from pathlib import Path
import cv2,numpy as np,mediapipe as mp
from teeth_geometry import INNER,curves,jaw_transform,mesh_points,mouth_stats

class NewTeethRestorer:
    def __init__(self,root='/work/data/teeth_20260930'):
        root=Path(root);self.manifest=json.loads((root/'manifest.json').read_text())
        self.donor_id=self.manifest['selected_donor'];metadata=self.manifest['candidates'][self.donor_id]
        asset=np.load(root/metadata['asset']);self.donor=asset['image'];self.points=asset['points']
        self.base_mesh=np.load(root/'base_mesh.npy');self.rois=np.load(root/'base_rois.npy')
        mask=np.zeros(self.donor.shape[:2],np.uint8);cv2.fillPoly(mask,[np.rint(self.points[list(INNER)]).astype(np.int32)],255)
        pixels=self.donor[mask>0];brightness=pixels.mean(axis=1)
        self.background=pixels[brightness<=np.percentile(brightness,25)].mean(axis=0).astype(np.float32)
        yy,xx=np.indices(mask.shape);top,bottom=curves(self.points,np.arange(mask.shape[1]))
        width=float(self.points[308,0]-self.points[78,0])
        # Keep the upper tooth band. Lower teeth belong to the moving jaw and
        # must not be imported as a second fixed row from a speaking donor.
        band=np.clip((top+width*.115-yy)/.75,0,1)*np.clip((yy-top)/.5,0,1)*(mask/255)
        self.donor=np.rint(self.donor*band[...,None]+self.background*(1-band[...,None])).clip(0,255).astype(np.uint8)
        self.transforms=np.asarray([jaw_transform(pts,self.points) for pts in self.base_mesh])
        self.mesh=mp.solutions.face_mesh.FaceMesh(max_num_faces=1,refine_landmarks=True,min_detection_confidence=.5,min_tracking_confidence=.5)
        self.reset()

    def reset(self):
        self.mesh.reset();self.visibility=0.;self.records=[]

    def process(self,image,index):
        begin=time.perf_counter();points=mesh_points(self.mesh,image,tuple(self.rois[index]))
        row={'replaced':False,'tracking_miss':points is None,'closed':False,'changed_pixels':0,'outside_lips_max_difference':0}
        if points is None:self.visibility=0.;return self.finish(image,row,begin)
        stats=mouth_stats(image,points)
        if stats is None:self.visibility=0.;return self.finish(image,row,begin)
        row.update(stats)
        opening=float(np.clip((stats['opening']-.025)/.065,0,1))
        visible=float(np.clip((stats['tooth_fraction']-.035)/.12,0,1))*opening
        self.visibility=.7*visible+.3*self.visibility
        strength=.85*min(self.visibility,opening)
        row['closed']=stats['opening']<=.025;row['strength']=strength
        if strength<.02:return self.finish(image,row,begin)
        polygon=points[list(INNER)]
        x0,y0=np.maximum(np.floor(polygon.min(axis=0)-2).astype(int),0)
        x1,y1=np.minimum(np.ceil(polygon.max(axis=0)+3).astype(int),image.shape[1::-1])
        xs=np.arange(x0,x1,dtype=np.float32);ys=np.arange(y0,y1,dtype=np.float32)[:,None]
        top,bottom=curves(points,xs);width=stats['width'];feather=max(.5,width*.010)
        upper=np.clip((ys-top-width*.004)/feather,0,1)
        lower=np.clip((bottom-width*.020-ys)/feather,0,1)
        sides=np.clip((xs-points[78,0])/feather,0,1)*np.clip((points[308,0]-xs)/feather,0,1)
        alpha=(upper*lower*sides)[...,None]*strength
        transform=self.transforms[index].copy();transform[:,2]-=[x0,y0]
        patch=cv2.warpAffine(self.donor,transform,(x1-x0,y1-y0),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_CONSTANT,borderValue=tuple(float(v) for v in self.background))
        # Hide the fixed tooth band behind the lower lip as the mouth closes.
        shadow=np.clip((bottom-width*.024-ys)/max(.5,width*.012),0,1)[...,None]
        patch=self.background+(patch.astype(np.float32)-self.background)*shadow
        original=image[y0:y1,x0:x1].copy()
        mixed=np.rint(original*(1-alpha)+patch*alpha).clip(0,255).astype(np.uint8)
        selected=alpha[:,:,0]>0
        image[y0:y1,x0:x1][selected]=mixed[selected]
        diff=np.abs(image[y0:y1,x0:x1].astype(np.int16)-original.astype(np.int16))
        row['outside_lips_max_difference']=int(diff[~selected].max()) if (~selected).any() else 0
        row['changed_pixels']=int((diff.max(axis=2)>0).sum());row['replaced']=row['changed_pixels']>0
        row['mouth_box']=[int(x0),int(y0),int(x1),int(y1)]
        return self.finish(image,row,begin)

    def finish(self,image,row,begin):
        row['ms']=(time.perf_counter()-begin)*1000;self.records.append(row);self.last=row
        return image

    def status(self):
        times=[row['ms'] for row in self.records]
        return {'donor':self.manifest['candidates'][self.donor_id],'frames':len(self.records),
                'restored_frames':sum(row['replaced'] for row in self.records),
                'tracking_misses':sum(row['tracking_miss'] for row in self.records),
                'closed_frames':sum(row['closed'] for row in self.records),
                'closed_frames_modified':sum(row['closed'] and row['changed_pixels']>0 for row in self.records),
                'outside_lips_max_difference':max([row['outside_lips_max_difference'] for row in self.records],default=0),
                'mean_ms':float(np.mean(times)) if times else None,'p95_ms':float(np.percentile(times,95)) if times else None}
