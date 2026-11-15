import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const require = createRequire(path.resolve(process.argv[2], 'package.json'));
const { restoreCache } = await import(pathToFileURL(require.resolve('@actions/cache')));
for (const { path: directory, key } of JSON.parse(process.env.NATIVE_CACHES)) {
  const restored = await restoreCache([directory], key);
  if (restored !== key) throw new Error(`Required native build cache is missing: ${key}`);
}
