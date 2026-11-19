import hashlib,json
from functools import lru_cache
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import balanced_accuracy_score,confusion_matrix

ALGORITHM='StandardScaler+KNeighborsClassifier(k=5,distance)'
SEED=42
NOTE='模拟标注训练，用于辅助试衣，不保证真实穿着舒适度'

def _dataset():
 rng=np.random.default_rng(SEED);X=[];y=[]
 for cls in ['合身','偏紧','偏松']:
  for i in range(100):
   elasticity=float(rng.uniform(0,1));cut=int(rng.integers(0,3));ease=float(rng.uniform(5,12) if cls=='合身' else rng.uniform(-5,1) if cls=='偏紧' else rng.uniform(17,26));shoulder=float(rng.uniform(.5,2.5) if cls=='合身' else rng.uniform(-3,-.5) if cls=='偏紧' else rng.uniform(4,7));X.append([ease,shoulder,elasticity,cut]);y.append(cls)
 ids=np.arange(len(y));tr,te=train_test_split(ids,test_size=.25,stratify=y,random_state=SEED)
 return np.array(X),np.array(y),tr,te

@lru_cache(maxsize=1)
def _trained():
 X,y,tr,te=_dataset();model=Pipeline([('scale',StandardScaler()),('knn',KNeighborsClassifier(n_neighbors=5,weights='distance'))]);model.fit(X[tr],y[tr]);pred=model.predict(X[te])
 meta={'algorithm':ALGORITHM,'seed':SEED,'balanced_accuracy':float(balanced_accuracy_score(y[te],pred)),'confusion_matrix':confusion_matrix(y[te],pred,labels=model.classes_).tolist(),'classes':model.classes_.tolist(),'train_count':len(tr),'holdout_count':len(te),'train_ids':tr.tolist(),'holdout_ids':te.tolist(),'training_sha256':hashlib.sha256(X.tobytes()+y.tobytes()).hexdigest(),'note':NOTE}
 return model,meta

def predict(measurement,profile):
 model,meta=_trained();features=[measurement['chest']-profile['chest'],measurement['shoulder']-profile['shoulder'],measurement['elasticity'],measurement['cut']];label=str(model.predict([features])[0]);probs=model.predict_proba([features])[0]
 return {**meta,'label':label,'features':features,'probabilities':{str(k):round(float(v),6) for k,v in zip(model.classes_,probs)},'source_sha256':hashlib.sha256(json.dumps([measurement,profile],sort_keys=True).encode()).hexdigest()}

def predict_batch(measurement,profile,adjustments):
 """Classify many (chest let-out cm, shoulder let-out cm) candidates with one fitted model."""
 model,meta=_trained();features=[[measurement['chest']+chest-profile['chest'],measurement['shoulder']+shoulder-profile['shoulder'],measurement['elasticity'],measurement['cut']] for chest,shoulder in adjustments]
 if not features:return [],[],meta
 probs=model.predict_proba(features);labels=[str(x) for x in model.predict(features)]
 return labels,probs,meta

def cheapest_fit(measurement,profile,chest_max_half,shoulder_max_half,chest_labor_cents,shoulder_labor_cents,chest_fabric_half,shoulder_fabric_half,available_half):
 """Search half-centimetre let-out steps with the size model, keep affordable fits, return the cheapest.

 Cheapest means least labour; ties prefer fewer half-centimetre steps, then less fabric. Fabric, capacity and
 stock are integers in half-centimetre units; labour is cents per half-centimetre step.
 """
 grid=[(c,s) for c in range(chest_max_half+1) for s in range(shoulder_max_half+1)]
 labels,probs,meta=predict_batch(measurement,profile,[(c/2,s/2) for c,s in grid]);idx=meta['classes'].index('合身')
 fit=[(c,s,float(probs[i][idx])) for i,(c,s) in enumerate(grid) if labels[i]=='合身']
 priced=[(c*chest_labor_cents+s*shoulder_labor_cents,c*chest_fabric_half+s*shoulder_fabric_half,c,s,p) for c,s,p in fit]
 affordable=[x for x in priced if x[1]<=available_half]
 min_fabric=min((x[1] for x in priced),default=None)
 detail={'model':{k:meta[k] for k in ['algorithm','seed','balanced_accuracy','train_count','holdout_count','note']},'candidates_checked':len(grid),'fit_candidates':len(fit),'min_fabric_half':min_fabric,'available_half':available_half,'chest_max_half':chest_max_half,'shoulder_max_half':shoulder_max_half}
 if not affordable:
  if fit:
   detail['message']=f'可放范围内最省布的合身改法也要 {min_fabric/2:g} cm 布，当前余布只有 {available_half/2:g} cm，找不到合身改法'
  else:
   detail['message']=f'在可放范围内（胸围 {chest_max_half/2:g} cm、肩宽 {shoulder_max_half/2:g} cm 以内）模型判定没有合身改法'
  return {'plan':None,'labor_cents':None,'fabric_half':None,**detail}
 labor,fabric,c,s,p=min(affordable,key=lambda x:(x[0],x[2]+x[3],x[1],x[2],x[3]))
 return {'plan':{'chest_half':c,'shoulder_half':s,'chest_cm':c/2,'shoulder_cm':s/2,'chest_labor_cents':c*chest_labor_cents,'shoulder_labor_cents':s*shoulder_labor_cents,'chest_fabric_half':c*chest_fabric_half,'shoulder_fabric_half':s*shoulder_fabric_half},'labor_cents':labor,'fabric_half':fabric,'probability':round(p,6),'affordable_candidates':len(affordable),**detail}
