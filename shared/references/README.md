# Shared references

Knowledge that more than one skill loads, written once. This file says what kinds of reference the folder holds and the rules for each; it lists no file, so that adding a reference edits nothing that exists.

Skills reference these files with a relative path from the skill folder (`../../shared/references/<file>`). Adapters that copy skills instead of linking them must copy `shared/references/` alongside.

Three kinds of file live here:

- **A transversal concern**, a file directly in this folder (`<concern>.md`): a checklist or a method that constrains work in every area, such as security. It states at the top which skills load it and at which step. One is added when a second skill needs the same knowledge, never speculatively.
- **A platform reference**, in `platforms/`: `<platform>.md`, what one social platform is as a medium, and `<platform>.json`, the same facts as data for scripts. One is written when the platform has a real task, never from general knowledge. The rules, the keys of a data file and the definition of which platform a step works on are in `platforms/README.md`.
- **A published vocabulary**, a pair of files directly in this folder (`<vocabulary>.md` and `<vocabulary>.json`): the closed list of values that the skills write and that a provider class draws or executes, such as `video-presets` (the animations a short video's script may ask for, and the renderer that draws them). The `.md` is what a model reads at the step that writes with the vocabulary; the `.json` is the same list as data, read by a checker and by the provider through a flag (`--presets <path>`), never found by a path of the script's own. The pair is one source: no skill and no provider holds a second copy of the list, and a test holds the two files equal. A vocabulary names no product and no harness, and holds no time, path or drawing rule of one implementation, so that a second implementation reads the same file. Adding a value edits the pair, never a skill's procedure; the skills that cite the file get a changed context, as below.

A change to a file here changes the context of the skills that read it: the lab evidence they made with the old file becomes inherited (the reliability model, "What a change costs"). A new file moves nothing.
