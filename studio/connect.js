'use strict';
const automatic=new URLSearchParams(location.search).get('tool')==='automatic',target=automatic?'/auto-dialogue.html':'/dialogue.html';
document.getElementById('open-local').href=target;
document.getElementById('connect-local').onclick=async()=>{const button=document.getElementById('connect-local'),state=document.getElementById('connect-state');button.disabled=true;try{const response=await fetch('/api/local-connect',{method:'POST',headers:{'X-SceneSound-Connect':'1'}}),data=await response.json();if(!response.ok)throw Error(data.error||'연결하지 못했어요.');location.replace('https://scenesound-mvp.vercel.app'+target+'#local='+encodeURIComponent(data.token));}catch(e){state.textContent=e.message;button.disabled=false;}};
