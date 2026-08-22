import test from "node:test";
import assert from "node:assert/strict";
import { captureReturnState, loadReaderPage, pageDeltaForGesture, pageOffset, restoreReturnState, revealLearningTarget, saveReaderPage } from "./reader_logic.mjs";

test("page persistence is scoped to a stable section", () => {
  const values=new Map(); const storage={getItem:(k)=>values.get(k),setItem:(k,v)=>values.set(k,v)};
  saveReaderPage(storage,"book:part",7); assert.equal(loadReaderPage(storage,"book:part"),7); assert.equal(loadReaderPage(storage,"book:other"),0);
});
test("one horizontal swipe advances one page and vertical gestures are locked", () => {
  assert.equal(pageDeltaForGesture(-80,4),1); assert.equal(pageDeltaForGesture(80,4),-1);
  assert.equal(pageDeltaForGesture(-80,100),0); assert.equal(pageDeltaForGesture(-20,0),0);
});
test("page offset is deterministic without free horizontal drift", () => { assert.equal(pageOffset(2,350),-780); });
test("return state restores exact scroll and focus", () => {
  const calls=[]; const focus={focus:(options)=>calls.push(["focus",options])};
  const win={scrollX:12,scrollY:987,scrollTo:(x,y)=>calls.push([x,y])};
  const state=captureReturnState(win,{activeElement:null},focus); restoreReturnState(win,state);
  assert.deepEqual(calls,[[12,987],["focus",{preventScroll:true}],[12,987]]);
});
test("course start reveals and focuses an already-selected lesson", () => {
  const scheduled=[]; const calls=[];
  const schedule=(callback)=>scheduled.push(callback);
  const target={
    focus:(options)=>calls.push(["focus",options]),
    scrollIntoView:(options)=>calls.push(["scroll",options]),
  };
  revealLearningTarget(target,schedule);
  assert.equal(scheduled.length,1); scheduled.shift()();
  assert.equal(scheduled.length,1); scheduled.shift()();
  assert.deepEqual(calls,[
    ["focus",{preventScroll:true}],
    ["scroll",{behavior:"smooth",block:"start"}],
  ]);
});
