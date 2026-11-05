# 仮想ゲーム盤でbotのループを回すシミュレーター
# 使い方: python tools/sim.py docs/board.jpg   （実機なしでループの挙動を確認）
import sys,types,cv2,numpy as np;sys.path.insert(0,'.');import kate_merge_bot as k
im=cv2.imread(sys.argv[1] if len(sys.argv)>1 else 'docs/board.jpg')
x0,y0,x1,y1=k.board_rect(im); cw,ch=(x1-x0)/7,(y1-y0)/9
def rect(c,r): return int(x0+c*cw),int(y0+r*ch),int(x0+(c+1)*cw),int(y0+(r+1)*ch)
def crop(c,r): a,b,e,f=rect(c,r); return im[b:f,a:e].copy()
SPR={'empty':None,'flour':crop(2,3),'butter':crop(3,3),'scoop':crop(0,4),'toast':crop(3,2),'dough':crop(2,5),'oven':crop(5,3),'box':crop(0,0)}
a,b,e,f=rect(2,3); teal=im[1300,100]
CHAIN={'flour':'butter','butter':'scoop','scoop':'dough','dough':'toast','toast':'toast'}
board={(c,r):'box' for c in range(7) for r in range(9)}
for c in range(7):
  for r in range(2,7): board[(c,r)]='empty'
board[(5,3)]='oven'; board[(0,2)]='flour'
state=dict(selected=False,taps=0,swipes=0,energy=40,log=[])
def render():
  t=im.copy()
  for (c,r),v in board.items():
    a,b,e,f=rect(c,r)
    if v=='empty': t[b:f,a:e]=teal
    else:
      s=cv2.resize(SPR[v],(e-a,f-b)); t[b:f,a:e]=s
  return t
def cell_at(p):
  c=int((p[0]-x0)//cw); r=int((p[1]-y0)//ch); return (c,r)
def tap(p):
  state['taps']+=1
  if cell_at(p)!=(5,3): return
  if not state['selected']: state['selected']=True; return   # 1回目は選択だけ
  if state['energy']<=0: return
  for key in sorted(board,key=lambda q:(q[1],q[0])):
    if board[key]=='empty': board[key]='flour'; state['energy']-=1; return
def swipe(p,q,ms=0):
  state['swipes']+=1; A,B=cell_at(p),cell_at(q)
  if board[A]==board[B] and board[A] in CHAIN:
    board[B]=CHAIN[board[A]]; board[A]='empty'; state['selected']=False
  state['log'].append('M')
orig_tap=tap
def tap_logged(p): orig_tap(p); state['log'].append('P')
k.screencap=render; k.tap=tap_logged; k.swipe=swipe; k.online_devices=lambda: ['sim']
clock=[0.0];k.time.time=lambda: clock[0]
def sl(s): clock[0]+=s
k.time.sleep=sl
args=types.SimpleNamespace(stop_file='/tmp/kate_sim_stop',start_delay=0,ignore_orders=True,save=None,no_view=True,produce=['5,3'],max_produce=0,cooldown=60,dry_run=False,max_hidden=15,max_merges=0,batch=8,swipe_ms=150,wait=0.35,verbose=False,burst=6,tap_interval=0.25,keep_empty=0,depleted_rest=30,max_idle=3,max_reconnect=0)
import io,contextlib
buf=io.StringIO()
with contextlib.redirect_stdout(buf): k.run(args)
out=buf.getvalue().splitlines()
print('\n'.join(out[:30])); print('...'); print('\n'.join(out[-8:]))
seq=''.join(state['log']); import re
print('操作列:',seq)
print('P/M切替回数:',len(re.findall(r'(P+M+)',seq)),' 経過(仮想)秒:',round(clock[0],1),' energy残:',state['energy'])
