from src.database import Base,engine,Session
from src.models import *
from src.security import password_hash
from src.common import rows

def seed():
 Base.metadata.create_all(engine)
 with Session() as s:
  for r in ['operator','supervisor','viewer']:
   if not any(u.email==r+'@hesheng.local' for u in rows(s,User)):s.add(User(email=r+'@hesheng.local',password=password_hash('Fit2026!'),role=r))
  if not s.get(Shop,1):s.add(Shop(id=1,now='2026-11-18T09:00:00'))
  if not any(g.code=='G031' for g in rows(s,Garment)):
   c=Consignor(name='林禾',contact='柜台留存联系单LH031');s.add(c);s.flush();prof=FitProfile(code='P031',chest=88,shoulder=37);s.add(prof);s.flush()
   for code,ends in [('A031','2026-11-26T18:00:00'),('A032','2026-11-20T18:00:00'),('A033','2026-11-17T18:00:00')]:s.add(Agreement(code=code,consignor_id=c.id,floor_cents=18000,commission_bp=2000,ends=ends))
   s.flush();ags=rows(s,Agreement)
   for code,title,ag,state in [('G031','烟苔绿短外套',ags[0],'listed'),('G032','复检中的棉衬衣',ags[1],'inspection'),('G033','期满未售针织衫',ags[2],'listed'),('G034','赭色直筒外套',ags[0],'listed')]:
    g=Garment(code=code,title=title,agreement_id=ag.id,condition='八成新，领口轻微使用痕迹，无破损',price_cents=22000,state=state);s.add(g);s.flush();s.add(Measurement(garment_id=g.id,chest=96,shoulder=39,length=58,elasticity=.2,cut=1))
   s.flush();g=next(g for g in rows(s,Garment) if g.code=='G032');f=Fitting(garment_id=g.id,profile_id=prof.id,slot=1,starts='2026-11-16T15:00:00',ends='2026-11-16T16:00:00',state='completed');s.add(f);s.flush();sale=Sale(fitting_id=f.id,garment_id=g.id,price_cents=22000,commission_bp=2000,commission_cents=4400,net_cents=17600,sold_at='2026-11-16T15:10:00',return_deadline='2026-11-23T15:10:00',state='returned');s.add(sale);s.flush();s.add(Return(sale_id=sale.id,reason='买家反馈肩部偏紧，已按原样退回待复检'))
  for code,chest,shoulder in [('P032',101,41),('P033',102,43)]:
   if not any(p.code==code for p in rows(s,FitProfile)):s.add(FitProfile(code=code,chest=chest,shoulder=shoulder))
  s.flush()
  if not s.get(FabricStock,1):s.add(FabricStock(id=1,stock_half=50))
  for code in ['G031','G034']:
   g=next((g for g in rows(s,Garment) if g.code==code),None)
   if g and not any(x.garment_id==g.id for x in rows(s,AlterationCapacity)):
    s.add(AlterationCapacity(garment_id=g.id,chest_max_half=16,shoulder_max_half=12,chest_labor_cents=120,shoulder_labor_cents=480,chest_fabric_half=2,shoulder_fabric_half=3))
  s.commit()
if __name__=='__main__':seed()
