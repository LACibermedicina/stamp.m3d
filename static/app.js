(()=>{'use strict';
/* ---------- util: HTML escapado por padrão ---------- */
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
class Raw{constructor(s){this.s=s}}
const raw=s=>new Raw(s);
const one=v=>v instanceof Raw?v.s:Array.isArray(v)?v.map(one).join(''):esc(v);
const html=(st,...v)=>new Raw(st.reduce((a,s,i)=>a+s+(i<v.length?one(v[i]):''),''));
const P={home:'<path d="M3 11 12 3l9 8v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',shield:'<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',plus:'<path d="M12 5v14M5 12h14"/>',tag:'<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".6"/>',search:'<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',chart:'<path d="M3 3v18h18"/><path d="M7 15v3M12 9v9M17 5v13"/>',users:'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',ticket:'<path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2z"/><path d="M13 5v2M13 17v2M13 11v2"/>',list:'<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',cog:'<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"/>',user:'<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',lock:'<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',out:'<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',dl:'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',key:'<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3"/>',ban:'<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',clock:'<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',alert:'<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4M12 17h.01"/>',film:'<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 3v18M17 3v18M3 12h18M3 7.5h4M3 16.5h4M17 7.5h4M17 16.5h4"/>',restore:'<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',check:'<path d="M20 6 9 17l-5-5"/>'};
const ic=n=>raw('<svg viewBox="0 0 24 24" width="1.15em" height="1.15em" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-.2em">'+(P[n]||'')+'</svg>');
const fmt=t=>t?new Date(t).toLocaleString('pt-BR'):'—';
const ROLE={adm:'Autorizador / Admin',req:'Solicitante / Autor'};
const STATUS={pending:['Aguardando aprovação','c-wait'],processing:['Processando','c-wait'],active:['Ativo','c-ok'],revoked:['Revogado','c-bad'],rejected:['Rejeitado','c-gray'],failed:['Falhou','c-bad']};
const ROB={std:'Conversão e recompressão',resize:'+ Redimensionamento',crop:'+ Corte (múltiplo de 8 px)'};
const chip=s=>html`<span class="chip ${STATUS[s][1]}">${s==='processing'||s==='pending'?raw('<i class="spin"></i>'):''}${STATUS[s][0]}</span>`;
const bchip=b=>html`<span class="badge-prev ${b.shape||'pill'}" style="background:${/^#[0-9a-f]{6}$/i.test(b.color)?b.color:'#7c6cf0'}">${b.icon?raw('<img alt="" style="width:18px;height:18px;border-radius:4px" src="'+esc(b.icon)+'">'):ic('check')}${b.text}</span>`;
const tile=(icn,grad,v,l)=>html`<div class="card tile" style="margin:0"><span class="ico" style="background:${grad}">${ic(icn)}</span><div><b>${v}</b><span>${l}</span></div></div>`;
const G={ok:'linear-gradient(135deg,#6ee7b7,#2dd4bf)',wait:'linear-gradient(135deg,#fcd34d,#fb923c)',bad:'linear-gradient(135deg,#fda4af,#f472b6)',info:'linear-gradient(135deg,#7dd3fc,#60a5fa)',pro:'linear-gradient(135deg,#a5b4fc,#a78bfa)',gray:'linear-gradient(135deg,#cbd5e1,#94a3b8)'};

/* ---------- estado e API ---------- */
const S={user:null,csrf:null,info:{},timer:null,lg:{tab:'in',tok:null,sent:false},keep:null};
const app=document.getElementById('app');
const toast=m=>{const t=document.createElement('div');t.className='toast';t.textContent=m;document.body.append(t);setTimeout(()=>t.remove(),3800)};
async function api(path,o={}){const h={...(o.headers||{})};let b=o.body;if(b&&!(b instanceof Blob)&&typeof b==='object'){b=JSON.stringify(b);h['Content-Type']='application/json'}
  const m=o.method||(b?'POST':'GET');if(S.csrf&&m!=='GET')h['X-CSRF-Token']=S.csrf;
  const r=await fetch(path,{method:m,headers:h,body:b,credentials:'same-origin'});const j=await r.json().catch(()=>({}));
  if(!r.ok){if(r.status===401&&S.user){S.user=null;S.csrf=null;go('login')}const e=new Error(j.error||('Erro '+r.status));e.status=r.status;throw e}return j}
const go=p=>{location.hash='#/'+p};
const TABS=u=>u?[['dash','home','Painel'],['stamps','shield','Selos'],['new','plus','Novo selo'],['badges','tag','Modelos'],['verify','search','Verificar'],...(u.role==='adm'?[['stats','chart','Estatísticas'],['users','users','Usuários'],['access','ticket','Acessos'],['audit','list','Auditoria'],['settings','cog','Config.']]:[]),['account','user','Conta']]:[['verify','search','Verificar (público)'],['login','lock','Entrar']];
const cubeSvg=()=>raw('<svg class="float" viewBox="-50 -50 100 100" width="46" height="46"><polygon points="0,-44 38.3,-22 0,0 -38.3,-22" fill="#ffd36b" stroke="#fff" stroke-width="3" stroke-linejoin="round"/><polygon points="-38.3,-22 0,0 0,44 -38.3,22" fill="#ff7a9c" stroke="#fff" stroke-width="3" stroke-linejoin="round"/><polygon points="38.3,-22 0,0 0,44 38.3,22" fill="#5cc8f2" stroke="#fff" stroke-width="3" stroke-linejoin="round"/></svg>');
const head=(page)=>html`<div class="top"><div class="brand">${cubeSvg()}<div>M3D<small>${S.info.site_name||'STAMP'}</small></div></div>${S.user?html`<div class="row"><div style="text-align:right;line-height:1.2"><b>${S.user.name}</b><div class="mut">${ROLE[S.user.role]}</div></div><button class="btn" data-act="logout">${ic('out')} Sair</button></div>`:html`<span class="mut">Verificação aberta a todos · login para emitir selos</span>`}</div><div class="tabs">${TABS(S.user).map(([k,i,t])=>html`<a class="btn ${page===k?'act':''}" href="#/${k}">${ic(i)} ${t}</a>`)}</div>`;
const card=(t,...c)=>html`<div class="card">${t?html`<h2>${t}</h2>`:''}${c}</div>`;
const table=(h,rows)=>html`<div class="scroll"><table><thead><tr>${h.map(x=>html`<th>${x}</th>`)}</tr></thead><tbody>${rows.map(r=>html`<tr>${r.map(c=>html`<td>${c}</td>`)}</tr>`)}</tbody></table></div>`;
const poll=(ms=3000)=>{clearTimeout(S.timer);S.timer=setTimeout(render,ms)};

/* ---------- páginas ---------- */
const PAGES={};
PAGES.login=async()=>{const L=S.lg;
  const tabs=[['in','Entrar'],['tok','Tenho um token'],['req','Pedir acesso']];
  const bar=html`<div class="grid" style="grid-template-columns:repeat(3,1fr);margin-bottom:14px">${tabs.map(([k,t])=>html`<button class="btn ${L.tab===k?'act':''}" data-act="lgtab" data-k="${k}">${t}</button>`)}</div>`;
  let body;
  if(L.tab==='in')body=html`<form data-form="login"><label class="f">E-mail</label><input name="email" type="email" autocomplete="username" required><label class="f">Senha</label><input name="password" type="password" autocomplete="current-password" required><p class="err" id="msg"></p><button class="btn pri">${ic('lock')} Entrar</button></form>`;
  else if(L.tab==='tok'&&!L.tok)body=html`<form data-form="tokcheck"><label class="f">Token de convite</label><input name="token" placeholder="VSI-XXXX-XXXX-XXXX" style="text-transform:uppercase;letter-spacing:.1em" required><p class="err" id="msg"></p><button class="btn pri">${ic('ticket')} Validar token</button><p class="mut">O cadastro só é liberado depois de um token válido emitido por um administrador. Cada token vale para uma única conta e expira.</p></form>`;
  else if(L.tab==='tok')body=html`<p class="chip c-ok">Token válido · ${ROLE[L.tok.role]}</p><form data-form="register"><label class="f">Nome completo</label><input name="name" required><label class="f">E-mail</label><input name="email" type="email" value="${L.tok.email}" ${L.tok.email?'readonly':''} required><label class="f">Senha (mín. 8)</label><input name="password" type="password" autocomplete="new-password" required minlength="8"><p class="err" id="msg"></p><div class="row"><button type="button" class="btn" data-act="tokreset">Trocar token</button><button class="btn pink">Criar conta e entrar</button></div></form>`;
  else if(!L.sent)body=S.info.allow_requests===false?html`<p class="mut">Os pedidos de acesso estão desativados.</p>`:html`<form data-form="request"><label class="f">Nome completo</label><input name="name" required><label class="f">E-mail</label><input name="email" type="email" required><label class="f">Perfil desejado</label><select name="role"><option value="req">Solicitante / Autor</option><option value="adm">Autorizador / Admin</option></select><label class="f">Por que precisa de acesso?</label><textarea name="reason" rows="3" maxlength="300" required></textarea><p class="err" id="msg"></p><button class="btn pri">Pedir acesso</button></form>`;
  else body=html`<p class="okmsg">Pedido enviado. Um administrador vai analisar e enviar um token de convite para o seu e-mail.</p><button class="btn" data-act="lgtab" data-k="in">Voltar</button>`;
  return html`<div class="card" style="max-width:460px;margin:0 auto"><h2>Acesso à plataforma</h2>${bar}${body}</div>`};

PAGES.dash=async()=>{const[st,ls]=await Promise.all([api('/api/stats'),api('/api/stamps')]),c=st.stamps,adm=S.user.role==='adm',n=k=>c[k]||0;
  if(ls.stamps.some(s=>s.status==='processing'))poll();
  return html`<div class="grid g4" style="margin-bottom:14px">${tile('shield',G.ok,n('active'),'Selos ativos')}${tile('clock',G.wait,n('pending')+n('processing'),'Aguardando / processando')}${tile('ban',G.bad,n('revoked'),'Removidos')}${tile('search',G.info,(st.verifications&&st.verifications.total)||0,'Verificações')}${adm?html`${tile('users',G.pro,st.users,'Usuários ativos')}${tile('ticket',G.wait,st.pending_requests,'Pedidos de acesso')}`:''}</div>
  ${card('Selos recentes',ls.stamps.length?ls.stamps.slice(0,6).map(s=>html`<div class="item row" style="justify-content:space-between"><div><b>${s.file_name}</b><div class="mut">${fmt(s.created)}${adm?' · '+s.owner_name:''}</div></div><div class="row">${bchip(s.badge)}${chip(s.status)}</div></div>`):html`<p class="mut">Nenhum selo ainda. Comece em <a href="#/new">Novo selo</a>.</p>`,html`<a class="btn" href="#/stamps">Ver todos</a>`)}`};

PAGES.stamps=async()=>{const{stamps}=await api('/api/stamps'),adm=S.user.role==='adm';
  if(stamps.some(s=>s.status==='processing'))poll();
  return card('Selos',stamps.length?stamps.map(s=>html`<div class="item"><div class="row" style="justify-content:space-between"><div><b>${s.file_name}</b><div class="mut">${s.public_id} · ${fmt(s.created)}${adm?' · '+s.owner_name:''} · ${ROB[s.robust]}</div><div class="mut">${s.purpose||''}</div></div><div class="row">${bchip(s.badge)}${chip(s.status)}</div></div>
   ${s.error?html`<p class="err">${s.error}</p>`:''}
   <div class="row" style="margin-top:8px">
    ${s.status==='pending'&&adm?html`<button class="btn sm pri" data-act="sact" data-id="${s.id}" data-a="approve">${ic('check')} Aprovar e assinar</button><button class="btn sm" data-act="sact" data-id="${s.id}" data-a="reject">Rejeitar</button>`:''}
    ${s.status==='active'?html`<a class="btn sm cy" href="/api/stamps/${s.id}/download">${ic('dl')} Baixar vídeo com selo</a>`:''}
    ${s.status==='active'&&adm?html`<a class="btn sm" href="/api/stamps/${s.id}/manifest">Manifesto</a><button class="btn sm" data-act="skey" data-id="${s.id}">${ic('key')} Chave QR</button><button class="btn sm" data-act="sact" data-id="${s.id}" data-a="revoke">${ic('ban')} Revogar</button>`:''}
    ${s.status==='revoked'&&adm?html`<button class="btn sm pri" data-act="sact" data-id="${s.id}" data-a="restore">${ic('restore')} Restaurar selo</button>`:''}
    ${s.status==='failed'&&adm?html`<button class="btn sm" data-act="sact" data-id="${s.id}" data-a="retry">Reprocessar</button>`:''}
    ${(adm||['pending','rejected','failed'].includes(s.status))&&s.status!=='processing'?html`<button class="btn sm" data-act="sdel" data-id="${s.id}">Excluir</button>`:''}
   </div></div>`):html`<p class="mut">Nenhum selo. <a href="#/new">Criar o primeiro</a>.</p>`)};

PAGES.new=async()=>{if(!S.info.engine)return card('Novo selo',html`<p class="err">O processamento de vídeo não está ativo neste servidor.</p><p class="mut">Instale ffmpeg, opencv-python-headless e numpy e reinicie o servidor (veja o README).</p>`);
  const{badges}=await api('/api/badges'),adm=S.user.role==='adm';
  return card('Novo selo',html`<form data-form="upload">
   <label class="f">1 · Vídeo (${S.info.max_upload_mb?'até '+S.info.max_upload_mb+' MB · ':''}MP4, MOV, MKV, WebM, AVI)</label><input type="file" name="file" accept="video/*,.mkv" required>
   <label class="f">2 · Modelo do selo</label><div class="row">${badges.map((b,i)=>html`<label class="opt" style="margin:0"><input type="radio" name="badge" value="${b.id}" ${i?'':'checked'}> ${bchip(b)}</label>`)}</div>
   <label class="f">3 · Transformações que o selo deve suportar (decida agora: depois não dá para mudar)</label>
   ${Object.entries({std:['Conversão de formato e recompressão','MP4, WebM, MKV · H.264, H.265, VP9. Mesma resolução e enquadramento.'],resize:['+ Redimensionamento','Reduzir (até ~40%), ampliar ou esticar. Não sobrevive a corte.'],crop:['+ Corte','Cortar bordas com deslocamento múltiplo de 8 px, sem mudar a escala. Não sobrevive a redimensionar.']}).map(([k,[t,d]],i)=>html`<label class="opt"><input type="radio" name="robust" value="${k}" ${i?'':'checked'}> <b>${t}</b><div class="mut">${d}</div></label>`)}
   <label class="f">4 · Finalidade</label><input name="purpose" placeholder="Ex.: Uso comercial — campanha de verão" maxlength="300" required>
   ${adm?html`<label class="row" style="margin-top:10px"><input type="checkbox" name="embed_qr"> Embutir a chave QR nos metadados do vídeo (quem tiver o arquivo poderá ler os dados do selo)</label>`:''}
   <label class="row" style="margin-top:10px"><input type="checkbox" name="declare" required> Declaro que sou o autor deste vídeo e me responsabilizo pelos dados do selo.</label>
   <p class="mut">O vídeo original nunca é alterado: o selo vai só numa cópia nova. ${adm?'Como Autorizador, o selo é assinado e processado na hora.':'Depois do envio, um Autorizador aprova e o vídeo é processado.'}</p>
   <div class="bar" id="pbar" style="display:none"><i style="width:0"></i></div><p class="err" id="msg"></p><button class="btn pink" id="sub">${ic('shield')} Enviar e criar selo</button></form>`)};

PAGES.badges=async()=>{const{badges}=await api('/api/badges'),adm=S.user.role==='adm';
  return html`${card('Modelos de selo',html`<div class="row">${badges.map(b=>html`<div class="row item" style="margin:0">${bchip(b)}${adm?html`<button class="btn sm" data-act="bdel" data-id="${b.id}" title="Remover">${ic('ban')}</button>`:''}</div>`)}</div>`)}
  ${adm?card('Novo modelo / importar',html`<form data-form="badge"><div class="grid g2"><div><label class="f">Texto (até 16)</label><input name="text" maxlength="16" required></div><div><label class="f">Nome</label><input name="name" maxlength="40"></div><div><label class="f">Cor</label><input name="color" type="color" value="#7c6cf0"></div><div><label class="f">Forma</label><select name="shape"><option value="pill">Pílula</option><option value="square">Quadrado</option><option value="shield">Escudo</option></select></div></div><label class="f">Ícone (PNG/JPG/WebP, opcional)</label><input type="file" name="icon" accept="image/png,image/jpeg,image/webp"><p class="err" id="msg"></p><div class="row"><button class="btn pri">Criar modelo</button><label class="btn">Importar JSON<input type="file" id="bimp" accept=".json" style="display:none"></label><button type="button" class="btn" data-act="bexp">Exportar JSON</button></div></form>`):''}`};

const vcell=(ok,t,v)=>html`<div class="card" style="margin:0;text-align:center;background:${ok?'#d1fae5':'#ffe4e6'}"><div style="font-size:12px;font-weight:800">${t}</div><b style="color:${ok?'#047857':'#be123c'}">${v}</b></div>`;
const vres=r=>html`<div class="grid" style="grid-template-columns:repeat(3,1fr);margin-top:14px">${vcell(r.present,'Selo',r.present?'PRESENTE':'AUSENTE')}${r.present?vcell(r.integrity==='intact','Integridade',r.integrity==='intact'?'ÍNTEGRO':'ALTERADO'):''}${r.present&&r.status?vcell(r.status==='valid','Status',r.status==='valid'?'VÁLIDO':'REVOGADO'):''}</div>
  ${r.present?html`<div class="item" style="margin-top:10px;font-size:13px;font-weight:700"><div>Hash SHA-256 do arquivo: ${r.layers.sha256?'confere com o registro':'diferente do registro'}</div><div>Esteganografia DCT: ${r.layers.dct===true?'detectada':r.layers.dct===false?'não detectada':'não analisada'}</div>${r.layers.qr_metadata?html`<div>QR de vinculação encontrado nos metadados do vídeo</div>`:''}<div class="mut">Referência pública: ${r.ref}</div></div>${r.integrity==='altered'?html`<p class="err">Selo identificado, mas o arquivo difere do emitido: foi convertido, recompactado ou editado.</p>`:''}<p class="chip c-wait">${ic('lock')} Dados do autor, solicitante e autorizador estão trancados.</p>`:html`<p class="mut">${r.note||'Nenhum selo reconhecido neste arquivo.'} Se o vídeo foi redimensionado, cortado ou convertido, o selo só é mantido quando essa transformação foi prevista ao emitir.</p>`}`;
PAGES.verify=async()=>{const adm=S.user&&S.user.role==='adm';
  return html`${card('Esse vídeo tem selo de verdade?',html`<p class="mut">Envie o vídeo (ou cole o hash SHA-256 do arquivo). Qualquer pessoa pode checar, sem ver dados pessoais.</p>${S.info.public_verify===false&&!S.user?html`<p class="err">A verificação pública está desativada.</p>`:html`<form data-form="verify"><label class="f">Vídeo</label><input type="file" name="file" accept="video/*,.mkv"><label class="f">…ou hash SHA-256</label><input name="hash" class="mono" placeholder="64 caracteres hexadecimais"><p class="err" id="msg"></p><button class="btn pri">${ic('search')} Verificar</button></form><div id="vres"></div>`}`)}
  ${adm?card('Destrancar com a chave QR (Autorizador/Admin)',html`<form data-form="unlock"><textarea name="key" rows="2" placeholder="Cole a chave VSI1:…" required></textarea><p class="err" id="msg"></p><button class="btn pink">${ic('key')} Destrancar</button></form><div id="ures"></div>`):''}`};
PAGES.pub=async(id)=>{const r=await api('/api/public/stamp/'+encodeURIComponent(id));
  return card('Consulta de selo',r.present?html`<p>${r.status==='valid'?html`<span class="chip c-ok">${ic('shield')} Selo VÁLIDO</span>`:html`<span class="chip c-bad">${ic('ban')} Selo REVOGADO</span>`}</p><p class="mut">Referência ${id.toUpperCase()} · emitido em ${r.issued_at}. Para confirmar um arquivo específico, use <a href="#/verify">Verificar</a>.</p>`:html`<p class="err">Nenhum selo com esta referência.</p>`)};

const kp=(k,v)=>html`<div class="row" style="justify-content:space-between;border-bottom:1px solid var(--bd);padding:4px 0"><span class="mut">${k}</span><b>${v}</b></div>`;
PAGES.stats=async()=>{const s=await api('/api/stats'),c=s.stamps,n=k=>c[k]||0,p=s.processing,v=s.verifications;
  return html`<div class="grid g4" style="margin-bottom:14px">${tile('shield',G.pro,s.total,'Selos solicitados')}${tile('check',G.ok,n('active'),'Ativos')}${tile('clock',G.wait,n('pending')+n('processing'),'Aguardando')}${tile('ban',G.bad,n('revoked'),'Removidos (revogados)')}${tile('users',G.info,s.requesters.length,'Requerentes')}${tile('search',G.info,v.total||0,'Verificações')}${tile('alert',G.bad,v.altered||0,'Alertas de adulteração')}${tile('film',G.ok,p.videos,'Vídeos processados')}${tile('clock',G.wait,(p.ms/1000).toFixed(1)+' s','Tempo de processamento')}${tile('dl',G.info,p.seconds.toFixed(1)+' s · '+p.mb.toFixed(1)+' MB','Total de vídeo selado')}</div>
  ${card('Requerentes',table(['Requerente','Selos','Ativos','Aguardando','Removidos','Última atividade'],s.requesters.map(r=>[r.name,r.total,r.active,r.waiting,r.removed,fmt(r.last)])))}
  ${card('Pendências de verificação (selos ativos nunca verificados)',s.never_verified.length?table(['Referência','Vídeo','Requerente','Emitido'],s.never_verified.map(x=>[x.public_id,x.file_name,x.owner_name,fmt(x.created)])):html`<p class="mut">Nenhuma pendência.</p>`)}
  ${card('Verificações públicas',kp('Total',v.total||0),kp('Sem selo',v.no_seal||0),kp('Arquivo alterado',v.altered||0))}`};

PAGES.users=async()=>{const{users}=await api('/api/admin/users');
  return html`${card('Criar usuário',html`<form data-form="newuser"><div class="grid g2"><input name="name" placeholder="Nome" required><input name="email" type="email" placeholder="E-mail" required><select name="role"><option value="req">Solicitante / Autor</option><option value="adm">Autorizador / Admin</option></select><input name="password" type="password" placeholder="Senha temporária (8+)" minlength="8" required autocomplete="new-password"></div><p class="err" id="msg"></p><button class="btn pri">${ic('plus')} Criar</button></form>`)}
  ${card('Usuários',table(['Nome','E-mail','Perfil','Estado','Último acesso','Ações'],users.map(u=>[u.name,u.email,html`<select data-change="urole" data-id="${u.id}">${Object.entries(ROLE).map(([k,t])=>html`<option value="${k}" ${u.role===k?'selected':''}>${t}</option>`)}</select>`,u.locked?'Bloqueado':u.active?'Ativo':'Desativado',fmt(u.last_login),html`<div class="row"><button class="btn sm" data-act="utog" data-id="${u.id}" data-v="${u.active?0:1}">${u.active?'Desativar':'Ativar'}</button><button class="btn sm" data-act="upw" data-id="${u.id}">Senha</button><button class="btn sm" data-act="udel" data-id="${u.id}">${ic('ban')}</button></div>`])))}`};

PAGES.access=async()=>{const[{invites},{requests}]=await Promise.all([api('/api/admin/invites'),api('/api/admin/requests')]),tok=S.keep;S.keep=null;
  const state=i=>i.revoked?'Revogado':i.used_at?'Usado':i.expires<new Date().toISOString()?'Expirado':'Ativo';
  return html`${tok?html`<div class="card" style="background:#fffbeb;border:2px solid #fcd34d"><b>Token gerado — copie agora, ele não será mostrado de novo:</b><input readonly data-sel value="${tok}" style="text-align:center;font-weight:900;letter-spacing:.12em;margin-top:8px"></div>`:''}
  ${card('Pedidos de acesso',requests.length?table(['Nome','E-mail','Perfil','Motivo','Data','Estado / ação'],requests.map(r=>[r.name,r.email,ROLE[r.role],r.reason,fmt(r.created),r.status==='pending'?html`<div class="row"><select id="rr${r.id}"><option value="req" ${r.role==='req'?'selected':''}>Solicitante</option><option value="adm" ${r.role==='adm'?'selected':''}>Autorizador</option></select><button class="btn sm pri" data-act="rapp" data-id="${r.id}">Aprovar</button><button class="btn sm" data-act="rden" data-id="${r.id}">Recusar</button></div>`:({approved:'Aprovado',denied:'Recusado'}[r.status])])):html`<p class="mut">Nenhum pedido.</p>`)}
  ${card('Convites (tokens de cadastro)',html`<form data-form="invite"><div class="grid g2"><select name="role"><option value="req">Solicitante / Autor</option><option value="adm">Autorizador / Admin</option></select><input name="email" placeholder="E-mail (opcional, vincula o token)"><select name="days"><option value="1">Vale 1 dia</option><option value="7" selected>Vale 7 dias</option><option value="30">Vale 30 dias</option></select></div><p class="err" id="msg"></p><button class="btn pink">${ic('ticket')} Gerar token</button></form>${table(['Nº','Perfil','E-mail','Validade','Estado',''],invites.map(i=>[i.id,ROLE[i.role],i.email||'qualquer',fmt(i.expires),state(i),state(i)==='Ativo'?html`<button class="btn sm" data-act="irev" data-id="${i.id}">Revogar</button>`:'']))}`)}`};

PAGES.audit=async()=>{const{events}=await api('/api/admin/events?limit=200');return card('Auditoria',table(['Data/hora','Evento','Referência','Detalhe','Usuário'],events.map(e=>[fmt(e.ts),html`<b>${e.type}</b>`,e.ref,e.info,e.user||'—'])))};

PAGES.settings=async()=>{const c=await api('/api/admin/settings'),e=c.engine;
  return card('Configurações',html`<form data-form="settings"><div class="grid g2"><div><label class="f">Nome do sistema</label><input name="site_name" value="${c.site_name}"></div><div><label class="f">Endereço público (URL)</label><input name="base_url" value="${c.base_url}"></div><div><label class="f">Envio máximo (MB)</label><input name="max_upload_mb" type="number" min="1" value="${c.max_upload_mb}"></div><div><label class="f">Sessão (horas)</label><input name="session_hours" type="number" min="1" value="${c.session_hours}"></div></div>
   ${[['public_verify','Verificação pública (sem login) ativa'],['allow_requests','Permitir pedidos de acesso'],['embed_qr_default','Embutir QR nos metadados dos vídeos de Solicitantes'],['secure_cookies','Cookies seguros (somente HTTPS)']].map(([k,t])=>html`<label class="row" style="margin-top:8px"><input type="checkbox" name="${k}" ${c[k]?'checked':''}> ${t}</label>`)}
   <p class="mut">Motor de selos: ${e.ok?'ativo':'INATIVO — '+e.why}</p><div class="row"><button class="btn pri">Salvar</button><a class="btn" href="/api/admin/backup">${ic('dl')} Baixar backup do banco (SQLite)</a></div></form>`)};

PAGES.account=async()=>card('Minha conta',html`<p><b>${S.user.name}</b><br><span class="mut">${S.user.email} · ${ROLE[S.user.role]}</span></p><h3>Alterar senha</h3><form data-form="pw"><input name="old" type="password" placeholder="Senha atual" required autocomplete="current-password"><div style="height:8px"></div><input name="new" type="password" placeholder="Nova senha (8+)" minlength="8" required autocomplete="new-password"><p class="err" id="msg"></p><button class="btn pri">Salvar nova senha</button></form>`);

/* ---------- render ---------- */
async function render(){clearTimeout(S.timer);
  const h=location.hash.replace(/^#\/?/,'').split('/'),p=h[0]||(S.user?'dash':'verify'),t=TABS(S.user);
  let page=p==='v'?'pub':t.some(x=>x[0]===p)?p:(S.user?'dash':'verify');
  if(S.user&&page==='login')page='dash';
  const act=document.activeElement&&document.activeElement.tagName==='INPUT'&&app.contains(document.activeElement);
  let body;try{body=await PAGES[page](h.slice(1).join('/'))}catch(e){body=card('',html`<p class="err">${e.message}</p>`)}
  if(act&&['dash','stamps'].includes(page))return;
  app.innerHTML=head(page==='pub'?'verify':page).s+body.s;
  const bi=document.getElementById('bimp');if(bi)bi.onchange=importBadges;
}
function msg(f,t){const m=f.querySelector('#msg');if(m)m.textContent=t||''}
const readDataUrl=(file,size=96)=>new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>{const im=new Image();im.onload=()=>{const c=document.createElement('canvas');c.width=c.height=size;c.getContext('2d').drawImage(im,0,0,size,size);res(c.toDataURL('image/png'))};im.onerror=()=>rej(new Error('Imagem inválida'));im.src=r.result};r.onerror=()=>rej(new Error('Falha ao ler imagem'));r.readAsDataURL(file)});
async function importBadges(e){const f=e.target.files[0];e.target.value='';if(!f)return;try{const j=JSON.parse(await f.text());const r=await api('/api/badges',{body:Array.isArray(j)?j:j.badges||[j]});toast(r.created+' modelo(s) importado(s)');render()}catch(er){toast('Arquivo inválido: '+er.message)}}
function download(name,data,type){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([data],{type}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000)}
const sha256=async f=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',await f.arrayBuffer()))].map(b=>b.toString(16).padStart(2,'0')).join('');

/* ---------- ações (cliques) ---------- */
const ACT={
 logout:async()=>{await api('/api/auth/logout',{method:'POST'}).catch(()=>{});S.user=null;S.csrf=null;S.lg={tab:'in',tok:null,sent:false};go('verify');render()},
 lgtab:b=>{S.lg.tab=b.dataset.k;S.lg.sent=false;render()},
 tokreset:()=>{S.lg.tok=null;render()},
 sact:async b=>{await api('/api/stamps/'+b.dataset.id+'/'+b.dataset.a,{method:'POST'});toast('Feito.');render()},
 sdel:async b=>{if(!confirm('Excluir este selo e os arquivos associados?'))return;await api('/api/stamps/'+b.dataset.id,{method:'DELETE'});render()},
 skey:async b=>{const k=await api('/api/stamps/'+b.dataset.id+'/key');const o=document.createElement('div');o.className='overlay';
   o.innerHTML=html`<div class="card"><h2>Chave QR de vinculação</h2><canvas id="qrc" style="max-width:100%"></canvas><p class="mut">O QR aponta para a consulta pública do selo. A chave abaixo destranca os dados (somente Autorizador/Admin).</p><textarea readonly data-sel rows="3" class="mono">${k.key}</textarea><div class="row" style="margin-top:8px"><button class="btn" id="kdl1">Baixar .txt</button><button class="btn" id="kdl2">Baixar QR (PNG)</button><button class="btn pri" id="kx">Fechar</button></div></div>`.s;
   document.body.append(o);const url=k.public_url.startsWith('http')?k.public_url:location.origin+'/#/v/'+k.public_url.split('/').pop();
   let M=null;try{const q=qrcode(0,'M');q.addData(url);q.make();const n=q.getModuleCount();M=Array.from({length:n},(_,y)=>Array.from({length:n},(_,x)=>q.isDark(y,x)))}catch(e){}
   const cv=o.querySelector('#qrc');if(M){const S8=8,Q=4,n=M.length;cv.width=cv.height=(n+2*Q)*S8;const c=cv.getContext('2d');c.fillStyle='#fff';c.fillRect(0,0,cv.width,cv.height);c.fillStyle='#27335b';M.forEach((r,y)=>r.forEach((on,x)=>on&&c.fillRect((x+Q)*S8,(y+Q)*S8,S8,S8)))}else cv.replaceWith(Object.assign(document.createElement('p'),{className:'mono',textContent:url}));
   o.querySelector('#kx').onclick=()=>o.remove();o.querySelector('#kdl1').onclick=()=>download('chave_qr.txt',k.key,'text/plain');o.querySelector('#kdl2').onclick=()=>M&&cv.toBlob(bl=>download('qr_selo.png',bl,'image/png'))},
 bdel:async b=>{if(!confirm('Remover este modelo?'))return;await api('/api/badges/'+b.dataset.id,{method:'DELETE'});render()},
 bexp:async()=>{const{badges}=await api('/api/badges');download('modelos_selos.json',JSON.stringify(badges.map(({name,text,emoji,color,shape,icon})=>({name,text,emoji,color,shape,icon})),null,2),'application/json')},
 utog:async b=>{await api('/api/admin/users/'+b.dataset.id,{method:'PUT',body:{active:b.dataset.v==='1'}});render()},
 upw:async b=>{const p=prompt('Nova senha temporária (mín. 8 caracteres):');if(!p)return;await api('/api/admin/users/'+b.dataset.id,{method:'PUT',body:{password:p}});toast('Senha redefinida.')},
 udel:async b=>{if(!confirm('Excluir este usuário?'))return;await api('/api/admin/users/'+b.dataset.id,{method:'DELETE'});render()},
 rapp:async b=>{const r=await api('/api/admin/requests/'+b.dataset.id+'/approve',{body:{role:document.getElementById('rr'+b.dataset.id).value}});S.keep=r.token;render()},
 rden:async b=>{await api('/api/admin/requests/'+b.dataset.id+'/deny',{method:'POST'});render()},
 irev:async b=>{await api('/api/admin/invites/'+b.dataset.id+'/revoke',{method:'POST'});render()}
};
document.addEventListener('click',async e=>{const b=e.target.closest('[data-act]');if(!b)return;e.preventDefault();try{await ACT[b.dataset.act](b)}catch(er){toast(er.message)}});
document.addEventListener('focusin',e=>{if(e.target&&e.target.hasAttribute&&e.target.hasAttribute('data-sel'))e.target.select()});
document.addEventListener('change',async e=>{const s=e.target.closest('[data-change]');if(s&&s.dataset.change==='urole'){try{await api('/api/admin/users/'+s.dataset.id,{method:'PUT',body:{role:s.value}});toast('Perfil atualizado.')}catch(er){toast(er.message);render()}}});

/* ---------- formulários ---------- */
const FORMS={
 login:async(f,d)=>{const r=await api('/api/auth/login',{body:{email:d.email,password:d.password}});S.user=r.user;S.csrf=r.csrf;go('dash');render()},
 tokcheck:async(f,d)=>{const r=await api('/api/auth/token',{body:{token:d.token}});S.lg.tok={...r,token:d.token};render()},
 register:async(f,d)=>{const r=await api('/api/auth/register',{body:{token:S.lg.tok.token,name:d.name,email:d.email,password:d.password}});S.user=r.user;S.csrf=r.csrf;S.lg.tok=null;go('dash');render()},
 request:async(f,d)=>{await api('/api/auth/request',{body:d});S.lg.sent=true;render()},
 upload:async(f,d,fd)=>{const file=f.file.files[0];if(!file)return msg(f,'Escolha um vídeo.');const bar=document.getElementById('pbar');bar.style.display='block';document.getElementById('sub').disabled=true;
   const meta={fileName:file.name,badge_id:+d.badge,robust:d.robust,purpose:d.purpose,embed_qr:!!f.embed_qr&&f.embed_qr.checked,declare:!!f.declare.checked};
   await new Promise((res,rej)=>{const x=new XMLHttpRequest();x.open('POST','/api/stamps/upload');x.setRequestHeader('Content-Type','application/octet-stream');x.setRequestHeader('X-CSRF-Token',S.csrf);x.setRequestHeader('X-Meta',encodeURIComponent(JSON.stringify(meta)));
     x.upload.onprogress=ev=>ev.lengthComputable&&(bar.firstChild.style.width=(ev.loaded/ev.total*100)+'%');
     x.onload=()=>{let j={};try{j=JSON.parse(x.responseText)}catch(e){}x.status<300?res(j):rej(new Error(j.error||('Erro '+x.status)))};x.onerror=()=>rej(new Error('Falha de rede'));x.send(file)}).catch(e=>{document.getElementById('sub').disabled=false;bar.style.display='none';throw e});
   toast('Enviado!');go('stamps')},
 badge:async(f,d)=>{const body={name:d.name,text:d.text,color:d.color,shape:d.shape};if(f.icon.files[0])body.icon=await readDataUrl(f.icon.files[0]);await api('/api/badges',{body});toast('Modelo criado.');render()},
 verify:async(f,d)=>{const out=document.getElementById('vres');out.innerHTML='<p class="mut"><i class="spin"></i> Analisando…</p>';const file=f.file.files[0],h=(d.hash||'').trim();if(!file&&!h){out.innerHTML='';return msg(f,'Envie um vídeo ou cole um hash.')}
   const r=file?await api('/api/public/verify',{method:'POST',body:file,headers:{'Content-Type':'application/octet-stream'}}):await api('/api/public/verify',{body:{sha256:h}});out.innerHTML=vres(r).s},
 unlock:async(f,d)=>{const r=await api('/api/admin/unlock',{body:{key:d.key}}),s=r.stamp;document.getElementById('ures').innerHTML=html`<div class="item">${kp('Vídeo',s.file_name)}${kp('Autor = Solicitante',r.author.name+' · '+r.author.email)}${kp('Autorizador',r.authorizer?r.authorizer.name:'—')}${kp('Finalidade',s.purpose)}${kp('Emitido em',fmt(s.created))}${kp('Estado',STATUS[s.status][0])}<div class="mono">Hc: ${r.hc}</div></div>`.s},
 newuser:async(f,d)=>{await api('/api/admin/users',{body:d});toast('Usuário criado.');render()},
 invite:async(f,d)=>{const r=await api('/api/admin/invites',{body:{...d,days:+d.days}});S.keep=r.token;render()},
 settings:async(f,d)=>{const b={site_name:d.site_name,base_url:d.base_url,max_upload_mb:+d.max_upload_mb,session_hours:+d.session_hours};for(const k of ['public_verify','allow_requests','embed_qr_default','secure_cookies'])b[k]=f[k].checked;await api('/api/admin/settings',{method:'PUT',body:b});S.info=await api('/api/public/info');toast('Configurações salvas.');render()},
 pw:async(f,d)=>{await api('/api/auth/password',{body:d});f.reset();toast('Senha alterada.')}
};
document.addEventListener('submit',async e=>{const f=e.target.closest('form[data-form]');if(!f)return;e.preventDefault();msg(f,'');const d=Object.fromEntries(new FormData(f).entries());
  try{await FORMS[f.dataset.form](f,d)}catch(er){msg(f,er.message);if(!f.querySelector('#msg'))toast(er.message)}});

/* ---------- início ---------- */
(async()=>{try{S.info=await api('/api/public/info')}catch(e){app.innerHTML='<p class="err">Servidor indisponível.</p>';return}
  try{const r=await api('/api/me');S.user=r.user;S.csrf=r.csrf}catch(e){}
  window.addEventListener('hashchange',render);render()})();
})();
