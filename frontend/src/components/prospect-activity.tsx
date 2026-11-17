import {time} from '@/lib/api';
import type {ProspectProgress} from '@/lib/prospect-pipeline';

export function ProspectActivity({activity,version}:{activity:ProspectProgress['latest_activity'];version?:number}){
 if(!activity&&!version)return null;
 return <p className="muted">
  {activity&&<>Latest action: {activity.label}{activity.at&&<> · <time dateTime={activity.at}>{time(activity.at)}</time></>}</>}
  {version!=null&&<>{activity?' · ':''}Draft v{version}</>}
 </p>;
}
