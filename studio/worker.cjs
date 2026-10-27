const http=require('node:http');
if(process.env.STUDIO_PUBLIC!=='1'||!process.env.STUDIO_WORKER_SECRET||process.env.STUDIO_WORKER_SECRET.length<32){console.error('Studio worker configuration missing');process.exit(1);}
const studio=require('./server.cjs');
const server=http.createServer(async(req,res)=>{
 res.status=c=>{res.statusCode=c;return res;};res.json=data=>{res.setHeader('Content-Type','application/json; charset=utf-8');res.end(JSON.stringify(data));};
 if(req.url==='/healthz'){res.setHeader('Cache-Control','no-store');return res.json({ok:true});}
 if(!req.url.startsWith('/api/studio/'))return res.status(404).json({error:'페이지를 찾을 수 없어요.'});
 await studio(req,res);
});
server.requestTimeout=10*60*1000;server.headersTimeout=60000;
server.listen(Number(process.env.PORT)||10000,'0.0.0.0',()=>console.log('Studio worker ready'));
