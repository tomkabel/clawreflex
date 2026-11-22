// Authoring metadata for OpenClaw's build/validate workflow. The implementation is
// shared with the dependency-free contract tests in index.mjs.
import { defineToolPlugin } from 'openclaw/plugin-sdk/tool-plugin';
import implementation from './index.mjs';
const definitions=[];
implementation.register({registerTool:tool=>definitions.push(tool)});
const entry=defineToolPlugin({
  id:implementation.id,
  name:implementation.name,
  description:'Sandboxed RED/reference/GREEN repair proposals with explicit Apply/Revert commands.',
  tools:tool=>definitions.map(definition=>tool({
    name:definition.name,label:definition.name,description:definition.description,
    parameters:definition.parameters,optional:true,
    execute:async params=>(await definition.execute('sdk',params)).details,
  })),
});
// Commands intentionally bypass model execution and preserve structured tool errors.
entry.register=api=>implementation.register(api);
export default entry;
