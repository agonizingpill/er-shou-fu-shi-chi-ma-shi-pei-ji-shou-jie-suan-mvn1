from sqlalchemy import select
from .models import *
from .common import *
from . import fit_model

DEFAULT_STOCK_HALF=100

def cm_to_half(v):
 h=int(round(v*2))
 if abs(h-v*2)>1e-9:fail('放宽量与用布量以半厘米为最小单位')
 return h

def summary(r):
 return {k:r[k] for k in ['plan','labor_cents','fabric_half','probability','candidates_checked','fit_candidates','min_fabric_half','available_half','chest_max_half','shoulder_max_half','message','affordable_candidates'] if k in r}|{'model':r['model']}

def capacity(s,d):
 lock(s);g=garment(s,d['garment_id'])
 if not any(m.garment_id==g.id for m in rows(s,Measurement)):fail('先完成实测，才能登记放宽能力')
 if g.state in ['sold','inspection','withdrawn']:fail('已售、待复检或已撤回衣物不登记放宽能力')
 vals={'garment_id':g.id,'chest_max_half':cm_to_half(d['chest_max_cm']),'shoulder_max_half':cm_to_half(d['shoulder_max_cm']),'chest_labor_cents':d['chest_labor_cents'],'shoulder_labor_cents':d['shoulder_labor_cents'],'chest_fabric_half':cm_to_half(d['chest_fabric_cm']),'shoulder_fabric_half':cm_to_half(d['shoulder_fabric_cm'])}
 if vals['chest_max_half']+vals['shoulder_max_half']==0:fail('胸围、肩宽至少要能放半厘米')
 x=next((x for x in rows(s,AlterationCapacity) if x.garment_id==g.id),None)
 if x:
  for k,v in vals.items():setattr(x,k,v)
 else:
  x=AlterationCapacity(**vals);s.add(x)
 s.flush();return x

def stock_row(s,for_update=False):
 q=select(FabricStock).where(FabricStock.id==1)
 if for_update:q=q.with_for_update().execution_options(populate_existing=True)
 x=s.scalars(q).first()
 if not x:
  x=FabricStock(id=1,stock_half=DEFAULT_STOCK_HALF);s.add(x);s.flush()
 return x

def adjust_stock(s,d):
 c=lock(s);st=stock_row(s,True);target=st.stock_half+cm_to_half(d['delta_cm'])
 if target<0:fail('调整后共享布条不能为负')
 s.add(FabricAdjustment(from_half=st.stock_half,to_half=target,reason=d['reason'],at=c.now));st.stock_half=target;s.flush()
 invalidate_stale(s);return st

def plan(s,g,p,cap,replaces_id=None,stock=None):
 m=next((m for m in rows(s,Measurement) if m.garment_id==g.id),None)
 if not m:fail('未实测服饰不能计算改法')
 st=stock if stock is not None else stock_row(s,True)
 r=fit_model.cheapest_fit(dump(m),dump(p),cap.chest_max_half,cap.shoulder_max_half,cap.chest_labor_cents,cap.shoulder_labor_cents,cap.chest_fabric_half,cap.shoulder_fabric_half,st.stock_half)
 fit=r['plan']
 q=AlterationQuote(garment_id=g.id,profile_id=p.id,chest_half=fit and fit['chest_half'],shoulder_half=fit and fit['shoulder_half'],labor_cents=r['labor_cents'],fabric_half=r['fabric_half'],stock_half=st.stock_half,state='quoted' if fit else 'no_fit',reason=r.get('message',''),replaces_id=replaces_id,result=summary(r))
 s.add(q);s.flush();return q

def replacement_of(s,qid):
 qs=[x for x in rows(s,AlterationQuote) if x.replaces_id==qid]
 return qs[-1] if qs else None

def ensure_replacement(s,q,st):
 rep=replacement_of(s,q.id)
 if rep:return rep
 cap=next((x for x in rows(s,AlterationCapacity) if x.garment_id==q.garment_id),None)
 if not cap:return None
 return plan(s,get(s,Garment,q.garment_id),get(s,FitProfile,q.profile_id),cap,replaces_id=q.id,stock=st)

def invalidate_stale(s):
 """Void every open quote the remaining shared fabric can no longer cover, re-quoting each on what is left.

 A quote for a garment already confirmed for someone else is voided without re-quoting: one garment cannot take two alterations.
 """
 st=stock_row(s,True);taken={x.garment_id for x in rows(s,AlterationQuote) if x.state=='confirmed'};new=[]
 for q in rows(s,AlterationQuote):
  if q.state!='quoted' or q.fabric_half is None:continue
  if q.garment_id in taken:
   q.state='invalid';q.invalid_cause='garment';q.reason=f'这件衣物已为其他买家确认改法（报价 #{next(x.id for x in rows(s,AlterationQuote) if x.garment_id==q.garment_id and x.state=="confirmed")}），同衣不能再改第二次'
   continue
  if q.fabric_half<=st.stock_half:continue
  q.state='invalid';q.invalid_cause='fabric';q.reason=f'共享布条现只剩 {st.stock_half/2:g} cm，不足此报价所需 {q.fabric_half/2:g} cm；旧报价失效，已按余布重算'
  rep=ensure_replacement(s,q,st)
  if rep:new.append(rep)
 return new

def quote(s,d):
 c=lock(s);g=garment(s,d['garment_id']);p=get(s,FitProfile,d['profile_id']);a=get(s,Agreement,g.agreement_id)
 if g.state not in ['listed','held']:fail('只在架或留衣衣物可报放宽改法')
 if time(c.now)>=time(a.ends):fail('寄售期已满，不再受理改衣报价')
 if any(x.garment_id==g.id and x.state=='confirmed' for x in rows(s,AlterationQuote)):fail('这件衣物已为其他买家确认改法，同衣不能再改第二次')
 cap=next((x for x in rows(s,AlterationCapacity) if x.garment_id==g.id),None)
 if not cap:fail('先登记这件衣服胸围、肩宽各能放多少，以及每半厘米工价和用布量')
 invalidate_stale(s)
 return plan(s,g,p,cap)

def confirm(s,qid,d,actor):
 c=lock(s)
 q=s.scalars(select(AlterationQuote).where(AlterationQuote.id==qid).with_for_update().execution_options(populate_existing=True)).first()
 if not q:raise HTTPException(404,'报价不存在')
 st=stock_row(s,True)
 prior=next((x for x in rows(s,AlterationConfirmation) if x.idempotency_key==d['idempotency_key']),None)
 if prior:
  if prior.quote_id!=q.id:fail('这个幂等键已用于另一份报价确认，请更换')
  return {'outcome':'replayed','message':'该确认此前已成功处理，未重复扣布','quote':dump(q),'confirmation':dump(prior),'stock_half':st.stock_half,'replacement':None}
 if any(x.quote_id==q.id for x in rows(s,AlterationConfirmation)):fail('这份报价已有确认记录，不能再次扣布')
 if q.state=='invalid':
  rep=ensure_replacement(s,q,st) if q.invalid_cause=='fabric' else None
  return {'outcome':'invalidated','message':q.reason,'quote':dump(q),'replacement':dump(rep) if rep else None,'stock_half':st.stock_half}
 if q.state!='quoted':fail(q.reason or '这份报价已失效，请按当前余布重新报价')
 if any(x.garment_id==q.garment_id and x.state=='confirmed' for x in rows(s,AlterationQuote)):fail('这件衣物已为其他买家确认改法，不能重复扣布')
 if q.fabric_half>st.stock_half:
  q.state='invalid';q.invalid_cause='fabric';q.reason=f'确认时共享布条只剩 {st.stock_half/2:g} cm，不足此报价所需 {q.fabric_half/2:g} cm；旧报价失效，已按余布重算'
  rep=ensure_replacement(s,q,st);invalidate_stale(s)
  return {'outcome':'invalidated','message':q.reason,'quote':dump(q),'replacement':dump(rep) if rep else None,'stock_half':st.stock_half}
 st.stock_half-=q.fabric_half;s.add(FabricAdjustment(from_half=st.stock_half+q.fabric_half,to_half=st.stock_half,reason=f'确认改衣报价 #{q.id} 扣布',at=c.now))
 x=AlterationConfirmation(quote_id=q.id,idempotency_key=d['idempotency_key'],fabric_half=q.fabric_half,labor_cents=q.labor_cents,actor=actor,confirmed_at=c.now);s.add(x);q.state='confirmed';s.flush()
 invalidate_stale(s)
 return {'outcome':'confirmed','message':f'确认成功，已扣共享布条 {q.fabric_half/2:g} cm','quote':dump(q),'confirmation':dump(x),'stock_half':st.stock_half,'replacement':None}
