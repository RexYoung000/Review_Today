# Dependencies and reference boundaries

- `@esotericsoftware/spine-canvas` / `spine-core` 4.2.120: Spine Runtimes License Agreement. Full notice retained in `licenses/Spine-Runtimes.txt`; generated local vendor bundle retains its copyright header. This is not an MIT runtime. Use/integration/distribution is governed by that license and the Spine Editor License Agreement. An MCP implementation does not grant a Spine editor or runtime license.
- `@modelcontextprotocol/sdk` 1.30.0: MIT. Used for stdio protocol, schema registration and client verification.
- `zod` 3.25.76: MIT. Input constraints.
- `sharp` 0.35.4: Apache-2.0 and bundled component notices. Reads geometry/source dimensions and rasterizes our code-native SVG attachments; not used to retouch the mascot bitmap.
- `@napi-rs/canvas` 1.0.8: MIT with its bundled component notices. Offline rendering.
- Local ffmpeg executable: optional for preview_clip. Its installed build/license governs that executable; no ffmpeg binary is distributed here.

No code from noncommercial `spine-animation-ai`, license-unconfirmed `zhoushengmin/spine-mcp-server`, or Blender MCP forks is included. No third-party hosted generation API is invoked by the tools. Only the one-time body image edit used the session's built-in imagegen tool.
