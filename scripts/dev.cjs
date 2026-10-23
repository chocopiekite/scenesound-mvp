const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {loadEnvFile} = require('node:process');
const root = path.join(__dirname,'..');
if (fs.existsSync(path.join(root,'.env.local'))) loadEnvFile(path.join(root,'.env.local'));
const analyze = require('../api/analyze.js');
const upload = require('../api/upload.js');
const sounds = require('../api/sounds.js');
http.createServer(async (req,res)=>{
  const route=new URL(req.url,'http://localhost').pathname;
  res.status = code=>{res.statusCode=code;return res;};
  res.json = data=>{res.setHeader('Content-Type','application/json; charset=utf-8');res.end(JSON.stringify(data));};
  if(route==='/api/sounds'){await sounds(req,res);return;}
  if(route==='/api/analyze'||route==='/api/upload'){
    const chunks=[];let length=0;
    try{for await(const chunk of req){length+=chunk.length;if(length>4300000){res.status(413).json({error:'3MB 이하의 영상을 선택해 주세요.'});return;}chunks.push(chunk);}req.body=chunks.length?JSON.parse(Buffer.concat(chunks).toString()):undefined;await (route==='/api/upload'?upload:analyze)(req,res);}catch{if(!res.writableEnded)res.status(400).json({error:'요청을 확인해 주세요.'});}return;
  }
  if(route==='/'||route==='/index.html'){res.setHeader('Content-Type','text/html; charset=utf-8');res.end(fs.readFileSync(path.join(root,'index.html')));return;}
  res.status(404).json({error:'페이지를 찾을 수 없어요.'});
}).listen(8001,'127.0.0.1',()=>console.log('Local: http://127.0.0.1:8001'));
