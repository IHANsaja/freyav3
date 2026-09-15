// Node 22.18+ / Node 24: node --experimental-strip-types --test test_scripts/trading_helpers.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {sizePracticeTrade,visibleRange} from '../freya-ui/app/trading/practiceMath.ts';
import {isDrawing} from '../freya-ui/app/trading/drawingTools.ts';
test('sizing includes costs and never exceeds chosen risk or available cash',()=>{
 const r=sizePracticeTrade(10000,10000,100,90,120,1,.001,.0005);
 assert(r);assert(r.estimatedLoss<=100);assert(r.units*100*1.0005*1.001<=10000);assert(r.ratio<2);
});
test('cash cap and invalid price ordering',()=>{
 const r=sizePracticeTrade(10000,50,100,90,120,1,0,0);assert.equal(r.units,.5);assert(r.cashLimited);
 for(const stop of [0,100,110,NaN])assert.equal(sizePracticeTrade(10000,10000,100,stop,120,1,0,0),null);
 assert.equal(sizePracticeTrade(10000,10000,100,90,120,101,0,0),null);
});
test('viewport filters use available bars only',()=>{
 assert.deepEqual(visibleRange([0,60,120,180],60,60),{from:2.5,to:3.5,limited:false});
 assert.equal(visibleRange([60,120],60,365*86400).limited,true);
 assert.equal(visibleRange([],60,3600),null);
});
test('drawing style validation keeps old objects readable',()=>{
 const d={id:'x',kind:'fibfan',points:[{time:1,price:100},{time:2,price:120}]};
 assert(isDrawing(d));assert(isDrawing({...d,locked:true,hidden:false,color:'#ffffff',width:4}));
 assert(!isDrawing({...d,color:'url(javascript:alert(1))'}));assert(!isDrawing({...d,width:500}));assert(!isDrawing({...d,rewardRatio:Infinity}));
});
