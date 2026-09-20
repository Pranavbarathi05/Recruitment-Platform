/**
 * Monaco Editor local bootstrap — the single place Monaco is configured.
 *
 * WHY THIS MODULE EXISTS
 *   `@monaco-editor/react` defaults to loading Monaco from the jsDelivr CDN
 *   at RUNTIME (`https://cdn.jsdelivr.net/npm/monaco-editor@x/min/vs`). The
 *   candidate-facing deployment runs on an isolated LAN where that fetch
 *   fails, so every coding editor stayed on its "Loading…" placeholder
 *   forever (production incident, Sept 2026). Importing the `monaco-editor`
 *   npm package here and handing it to `loader.config({ monaco })` removes
 *   the CDN entirely: Monaco is bundled by Vite, version-locked by
 *   package.json, and served same-origin like every other asset.
 *
 * WORKERS
 *   Monaco forks Web Workers for tokenization/intellisense. With the ESM
 *   build the worker entry points must be wired explicitly through
 *   `self.MonacoEnvironment`, otherwise worker creation fails at runtime.
 *   Vite's `?worker` imports emit each worker as a separate hashed chunk
 *   that works in both dev and the production build. The editor worker is
 *   required; the json/css/html/typescript workers are only fetched when
 *   those languages are actually used (lazily — they cost nothing up front
 *   but must exist so a future rich-language feature cannot reintroduce a
 *   permanent hang).
 *
 * LANGUAGE COVERAGE
 *   The assessment offers Python 3, C++, Java and C. `monaco-editor`'s
 *   `cpp` basic-language contribution registers BOTH the `c` and `cpp`
 *   language ids, so C highlighting ships through that one import. Rich
 *   (worker-backed) languages are intentionally NOT registered.
 */
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api';
import { loader } from '@monaco-editor/react';

import 'monaco-editor/esm/vs/basic-languages/python/python.contribution.js';
import 'monaco-editor/esm/vs/basic-languages/cpp/cpp.contribution.js';
import 'monaco-editor/esm/vs/basic-languages/java/java.contribution.js';

import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker';
import cssWorker from 'monaco-editor/esm/vs/language/css/css.worker?worker';
import htmlWorker from 'monaco-editor/esm/vs/language/html/html.worker?worker';
import tsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker';

// Must be installed before any editor instance is created.
self.MonacoEnvironment = {
  getWorker(_workerId, label) {
    switch (label) {
      case 'json':
        return new jsonWorker();
      case 'css':
      case 'scss':
      case 'less':
        return new cssWorker();
      case 'html':
      case 'handlebars':
      case 'razor':
        return new htmlWorker();
      case 'typescript':
      case 'javascript':
        return new tsWorker();
      default:
        // python / c / cpp / java and every basic language use the core editor worker.
        return new editorWorker();
    }
  },
};

// Point @monaco-editor/react at the LOCAL monaco instance. After this call
// the loader never touches a CDN — the editor renders from the bundle.
loader.config({ monaco });

export { monaco };
