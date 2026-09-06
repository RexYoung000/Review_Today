import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
export const toolRoot=fileURLToPath(new URL('../',import.meta.url));
export const root=resolve(toolRoot,'../..');
export const previewRoot=resolve(root,'brand/refresh-2026-09/motion-rig');
export const workRoot=process.env.MASCOT_WORK_DIR?resolve(process.env.MASCOT_WORK_DIR):resolve(toolRoot,'.work');
