// Shared by the browser and regression checks: preserve the current depth layer
// until the detached ball has faded into the rest pose.
export function createReturnState(runtime,rig,time){
  const data=new runtime.AnimationStateData(rig.data);data.defaultMix=.22;
  const state=new runtime.AnimationState(data),old=state.setAnimation(0,'recall',false);
  old.trackTime=time;old.timeScale=0;old.mixDrawOrderThreshold=1;
  state.apply(rig.skeleton);state.setAnimation(0,'rest',false);return state;
}
