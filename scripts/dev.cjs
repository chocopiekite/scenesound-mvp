const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {loadEnvFile} = require('node:process');
const {execFileSync}=require('node:child_process');
const root = path.join(__dirname,'..');
if (fs.existsSync(path.join(root,'.env.local'))) loadEnvFile(path.join(root,'.env.local'));
// Local prototype key lives in macOS Keychain, never in the repository.
if(!process.env.EPIDEMIC_API_KEY&&process.platform==='darwin')try{process.env.EPIDEMIC_API_KEY=execFileSync('/usr/bin/security',['find-generic-password','-s','scenesound-mvp-epidemic-test','-w'],{encoding:'utf8',stdio:['ignore','pipe','pipe']}).trim();}catch{}
if(process.env.EPIDEMIC_API_KEY&&!process.env.FREESOUND_API_KEY)process.env.FREESOUND_PRODUCTION_PROXY='true';
const analyze = require('../api/analyze.js');
const esPreview=require('../api/epidemic-preview.js');
const soundEvents=require('../api/sound-events.js');
const upload = require('../api/upload.js');
const sounds = require('../api/sounds.js');
http.createServer(async (req,res)=>{
  const route=new URL(req.url,'http://localhost').pathname;
  res.status = code=>{res.statusCode=code;return res;};
  res.json = data=>{res.setHeader('Content-Type','application/json; charset=utf-8');res.end(JSON.stringify(data));};
  if(route==='/api/epidemic-preview'){await esPreview(req,res);return;}
  if(route==='/api/sounds'){await sounds(req,res);return;}
  if(process.env.EPIDEMIC_API_KEY&&!process.env.TWELVELABS_API_KEY&&['/api/analyze','/api/upload'].includes(route)){
    try{const chunks=[];let size=0;for await(const c of req){size+=c.length;if(size>4300000){res.status(413).json({error:'요청이 너무 커요.'});return;}chunks.push(c);}const upstream=await fetch('https://scenesound-mvp.vercel.app'+route,{method:req.method,headers:{'Content-Type':'application/json'},...(chunks.length?{body:Buffer.concat(chunks)}:{}),signal:AbortSignal.timeout(280000)});res.status(upstream.status).json(await upstream.json());}catch{res.status(502).json({error:'공개 영상 분석 서버에 연결하지 못했어요.'});}return;
  }
  if(route==='/api/analyze'||route==='/api/upload'||route==='/api/sound-events'){
    const chunks=[];let length=0;
    try{for await(const chunk of req){length+=chunk.length;if(length>4300000){res.status(413).json({error:'3MB 이하의 영상을 선택해 주세요.'});return;}chunks.push(chunk);}req.body=chunks.length?JSON.parse(Buffer.concat(chunks).toString()):undefined;await (route==='/api/upload'?upload:route==='/api/sound-events'?soundEvents:analyze)(req,res);}catch{if(!res.writableEnded)res.status(400).json({error:'요청을 확인해 주세요.'});}return;
  }
  if(route==='/'||route==='/index.html'){res.setHeader('Content-Type','text/html; charset=utf-8');res.end(fs.readFileSync(path.join(root,'index.html')));return;}
  res.status(404).json({error:'페이지를 찾을 수 없어요.'});
}).listen(8001,'127.0.0.1',()=>console.log('Local: http://127.0.0.1:8001'));
