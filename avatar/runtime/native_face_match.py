"""110-point mouth-local compositing; preserve native nose, cheek and jaw pixels."""
import cv2
import numpy as np


class NativeFaceMatch:
    def __init__(self):
        self.field = None

    def prepare(self, image, landmarks, bbox):
        assert landmarks.shape == (110, 2), 'This model uses the supplied 110-point layout'
        x1,y1,x2,y2 = map(int,bbox)
        pts = (landmarks-[x1,y1])*[152/(x2-x1),152/(y2-y1)]-4
        # Verified against upstream mean_face.txt: lips 90..109, nose 51..65.
        mouth=pts[90:110];lo=mouth.min(0);hi=mouth.max(0);center=(lo+hi)/2
        lip_width=hi[0]-lo[0]
        assert lip_width>15 and center[1]>pts[60,1]
        yy,xx=np.mgrid[:144,:144].astype(np.float32)
        rx=lip_width/2+7
        ry=max((hi[1]-lo[1])/2+7,lip_width*.37)
        r=np.sqrt(((xx-center[0])/rx)**2+((yy-center[1])/ry)**2)
        # A fully generated central opening, with a short curved transition.
        t=np.clip((1.25-r)/.30,0,1)
        alpha=t*t*(3-2*t)
        # Do not touch the original nose even at the top of the curved support.
        top=max(float(pts[60,1]+4),float(lo[1]-8))
        u=np.clip((yy-top)/6,0,1);alpha*=u*u*(3-2*u)
        skin=np.zeros((144,144),np.float32)
        cv2.fillConvexPoly(skin,cv2.convexHull(pts[:33].astype(np.int32)),1)
        # Observe nearby skin, excluding all lips / opening and the full nose.
        skin[r<1.35]=0
        nose=np.zeros_like(skin)
        cv2.fillConvexPoly(nose,cv2.convexHull(pts[51:66].astype(np.int32)),1)
        nose=cv2.dilate(nose,np.ones((7,7),np.uint8));skin*=1-nose
        skin[:5]=0;skin[-5:]=0;skin[:,:5]=0;skin[:,-5:]=0
        assert skin.sum()>100
        support=cv2.GaussianBlur(skin,(0,0),10)[...,None]
        alpha152=np.pad(alpha,((4,4),(4,4)))
        native_alpha=cv2.resize(alpha152,(x2-x1,y2-y1),interpolation=cv2.INTER_LINEAR)[...,None]
        # Explicitly identify pixels that must stay native, not merely close.
        return {'skin':skin[...,None],'support':support,'alpha':native_alpha,'bbox':(x1,y1,x2,y2),'patch_alpha':alpha,'mouth_points':mouth,'native':image[y1:y2,x1:x2]}

    def apply(self,prediction,reference,prepared):
        residual=np.clip(reference.astype(np.float32)-prediction.astype(np.float32),-48,48)
        field=cv2.GaussianBlur(residual*prepared['skin'],(0,0),10)/np.maximum(prepared['support'],.001)
        field=np.clip(field,-36,36)
        self.field=field if self.field is None else .8*self.field+.2*field
        corrected=np.clip(prediction.astype(np.float32)+self.field,0,255)
        # No closed native mouth is copied into the generated central opening.
        patch=np.pad(corrected,((4,4),(4,4),(0,0)),mode='edge')
        x1,y1,x2,y2=prepared['bbox']
        enlarged=cv2.resize(patch,(x2-x1,y2-y1),interpolation=cv2.INTER_LINEAR)
        alpha=prepared['alpha'];native=prepared['native']
        roi=np.rint(enlarged*alpha+native.astype(np.float32)*(1-alpha)).clip(0,255).astype(np.uint8)
        roi[alpha[...,0]==0]=native[alpha[...,0]==0]
        return roi
