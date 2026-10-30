import test from 'node:test';
import assert from 'node:assert/strict';
import { modelAdvice } from '../voice/modelHardwareAdvice.js';
const GiB=1024**3;
const models=[{id:'standard',guidance:{reference_memory_bytes:2*GiB,validation:{state:'passed'}}},
              {id:'small',guidance:{reference_memory_bytes:GiB,validation:{state:'passed'}}}];
const gpu=(free,total=8*GiB,kind='gpu')=>({name:'Vulkan0',kind,description:'GPU',memory_total:total,memory_free:free});
const snapshot=(devices)=>({phase:'ready',devices,measured_at_ms:1000});
const advise=(hardware,extra={})=>modelAdvice(models,hardware,{now:1000,reserveBytes:GiB,...extra});
test('select standard or small using current free memory plus margin, never total alone',()=>{
  assert.equal(advise(snapshot([gpu(4*GiB)])).recommended,'standard');
  assert.equal(advise(snapshot([gpu(2.5*GiB)])).recommended,'small');
  const low=advise(snapshot([gpu(.5*GiB)]));assert.equal(low.recommended,null);assert.equal(low.reason,'low_memory');
});
test('zero free is exhausted; missing/free stale/shared are unknown',()=>{
  assert.equal(advise(snapshot([gpu(0)])).reason,'low_memory');
  assert.equal(advise(snapshot([gpu(null)])).reason,'unknown_memory');
  assert.equal(advise(snapshot([gpu(4*GiB,8*GiB,'igpu')])).reason,'shared_memory');
  assert.equal(advise(snapshot([gpu(4*GiB)]),{now:121001}).reason,'stale');
});
test('does not add GPU memory or recommend the second GPU which runtime will not select',()=>{
  const result=advise(snapshot([gpu(.5*GiB),{...gpu(8*GiB),name:'Vulkan1'}]));
  assert.equal(result.device.name,'Vulkan0');assert.equal(result.recommended,null);assert.equal(result.multiple,true);
});
test('CPU mode, unavailable probe and not yet tested variants cannot claim GPU suitability',()=>{
  assert.equal(advise(snapshot([gpu(8*GiB)]),{deviceMode:'cpu'}).reason,'cpu');
  assert.equal(advise(snapshot([{kind:'cpu'}])).reason,'cpu');
  assert.equal(advise({phase:'failed',devices:[]}).reason,'unknown');
  assert.equal(modelAdvice([{id:'pending',guidance:{reference_memory_bytes:GiB,validation:{state:'pending'}}}],snapshot([gpu(8*GiB)]),{now:1000,reserveBytes:GiB}).recommended,null);
});
