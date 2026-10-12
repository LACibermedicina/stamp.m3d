(()=>{'use strict';
const root=document.getElementById('inst');
const el=(t,a={},...k)=>{const e=document.createElement(t);for(const[x,v]of Object.entries(a)){if(x==='class')e.className=v;else if(x==='on')for(const[ev,fn]of Object.entries(v))e.addEventListener(ev,fn);else if(v!==false&&v!=null)e.setAttribute(x,v===true?'':v)}for(const c of k.flat())e.append(c.nodeType?c:document.createTextNode(c));return e};
const api=async(p,o={})=>{const r=await fetch(p,{method:o.body?'POST':'GET',headers:o.body?{'Content-Type':'application/json'}:{},body:o.body?JSON.stringify(o.body):undefined});const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||('Erro '+r.status));return j};
const cube=()=>{const ns='http://www.w3.org/2000/svg',s=document.createElementNS(ns,'svg');s.setAttribute('viewBox','-50 -50 100 100');s.setAttribute('width','46');s.setAttribute('height','46');s.classList.add('float');
 const r=44,F={'#ffd36b':[[0,-r],[.87*r,-.5*r],[0,0],[-.87*r,-.5*r]],'#ff7a9c':[[-.87*r,-.5*r],[0,0],[0,r],[-.87*r,.5*r]],'#5cc8f2':[[.87*r,-.5*r],[0,0],[0,r],[.87*r,.5*r]]};
 for(const[c,p]of Object.entries(F)){const g=document.createElementNS(ns,'polygon');g.setAttribute('points',p.map(q=>q.join(',')).join(' '));g.setAttribute('fill',c);g.setAttribute('stroke','#fff');g.setAttribute('stroke-width','3');s.append(g)}return s};
const brand=()=>el('div',{class:'brand',style:'margin-bottom:14px'},cube(),el('div',{},'M3D',el('small',{},'STAMP · INSTALADOR')));
let step=1,checks=[],form={site_name:'M3D Stamp',base_url:location.origin,admin_name:'',admin_email:'',admin_password:'',pw2:'',code:'',max_upload_mb:500,session_hours:8,public_verify:true,secure_cookies:location.protocol==='https:'},msg='';
const stepsBar=()=>el('div',{class:'steps'},...['1 Ambiente','2 Configuração','3 Concluído'].map((t,i)=>el('div',{class:step===i+1?'on':step>i+1?'done':''},t)));
const field=(label,key,type='text',extra={})=>[el('label',{class:'f'},label),el('input',{type,value:form[key]??'',autocomplete:type==='password'?'new-password':'off',...extra,on:{input:e=>{form[key]=type==='number'?+e.target.value:e.target.value}}})];
const check=(key,label)=>el('label',{class:'row',style:'margin-top:10px;font-size:14px'},el('input',{type:'checkbox',checked:form[key],on:{change:e=>{form[key]=e.target.checked}}}),label);
async function render(){
 root.replaceChildren(brand(),stepsBar());
 if(step===1){
  const c=el('div',{class:'card'},el('h2',{},'Bem-vindo(a)!'),el('p',{class:'mut'},'Este assistente verifica o servidor, cria o banco de dados SQLite e a conta administradora. Leva menos de um minuto.'));
  try{checks=(await api('/api/install/check')).checks}catch(e){c.append(el('p',{class:'err'},e.message));root.append(c);return}
  for(const k of checks)c.append(el('div',{class:'item row',style:'justify-content:space-between'},el('span',{},(k.ok?'✅ ':k.required?'❌ ':'⚠️ ')+k.name),k.ok?'':el('span',{class:'mut'},k.hint)));
  const bad=checks.some(k=>k.required&&!k.ok),warn=checks.some(k=>!k.required&&!k.ok);
  if(warn)c.append(el('p',{class:'mut'},'⚠️ Sem ffmpeg/OpenCV/NumPy o sistema funciona (usuários, convites, registro), mas NÃO processa vídeos nem lê selos em arquivos. Instale e reinicie o servidor quando quiser ativar.'));
  c.append(el('div',{class:'row',style:'margin-top:12px'},el('button',{class:'btn',on:{click:render}},'Verificar de novo'),el('button',{class:'btn pri',disabled:bad,on:{click:()=>{step=2;msg='';render()}}},'Continuar ›')));
  root.append(c);return}
 if(step===2){
  const c=el('div',{class:'card'},el('h2',{},'Configuração'),
   ...field('Código de instalação (mostrado no terminal do servidor e em data/INSTALL_CODE.txt)','code','text',{placeholder:'XXXX-XXXX'}),
   ...field('Nome do sistema','site_name'),...field('Endereço público (URL)','base_url'),
   el('h3',{style:'margin-top:16px'},'Conta administradora'),...field('Nome','admin_name'),...field('E-mail','admin_email','email'),...field('Senha (mín. 10 caracteres)','admin_password','password'),...field('Repita a senha','pw2','password'),
   el('h3',{style:'margin-top:16px'},'Preferências'),check('public_verify','Permitir verificação pública (sem login)'),check('secure_cookies','Estou usando HTTPS (cookies seguros)'),
   ...field('Tamanho máximo de envio (MB)','max_upload_mb','number',{min:1}),...field('Duração da sessão (horas)','session_hours','number',{min:1}),
   msg?el('p',{class:'err'},msg):'',
   el('div',{class:'row',style:'margin-top:12px'},el('button',{class:'btn',on:{click:()=>{step=1;render()}}},'‹ Voltar'),el('button',{class:'btn pink',on:{click:async e=>{
     if(form.admin_password!==form.pw2){msg='As senhas não conferem.';return render()}
     e.target.disabled=true;e.target.textContent='Instalando…';
     try{await api('/api/install',{body:form});step=3;render()}catch(er){msg=er.message;render()}}}},'✨ Instalar')));
  root.append(c);return}
 root.append(el('div',{class:'card'},el('h2',{},'✅ Instalação concluída'),el('p',{},'O banco de dados e a conta administradora foram criados e o instalador foi desativado.'),
  el('ul',{class:'mut'},el('li',{},'Entre com o e-mail e a senha que você acabou de definir.'),el('li',{},'Crie convites e contas em "Acessos" e "Usuários".'),el('li',{},'Faça backup periódico da pasta data/ (ou pelo botão em Configurações).')),
  el('a',{class:'btn pri',href:'/'},'Ir para o sistema ›')));
}
render();
})();
