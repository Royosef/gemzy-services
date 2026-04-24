# Prompting Package

Shared prompt registry helpers and prompt-definition data used by the Gemzy API
and the shared generation server.

## Local install

From a service directory:

```sh
pip install -e ../../packages/prompting
```

The package now owns the shared on-model and pure-jewelry prompt definition
modules, so API services no longer need to depend on the generation-server
package just to load prompt metadata.
