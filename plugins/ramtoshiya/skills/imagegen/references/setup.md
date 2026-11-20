# Setup routes

| Route | Environment |
| --- | --- |
| A local proxy that serves both providers, such as CLIProxyAPI | `IMAGEGEN_BASE_URL=http://127.0.0.1:8317/v1` and `IMAGEGEN_API_KEY` set to one of the proxy's `api-keys` |
| OpenAI API | `OPENAI_API_KEY`, optionally `OPENAI_BASE_URL` |
| xAI API | `XAI_API_KEY`, optionally `XAI_BASE_URL` |

`IMAGEGEN_BASE_URL` takes priority for every model when it is set.
