# Changelog

## [0.5.0](https://github.com/stritti/ptz-simulator/compare/v0.4.0...v0.5.0) (2026-11-07)


### Features

* **skills:** add pelco-d-interface skill ([fb31471](https://github.com/stritti/ptz-simulator/commit/fb31471659890b0da2a070a5554896a6505ff2c8))


### Bug Fixes

* **skills:** address pelco-d review round ([0baedbd](https://github.com/stritti/ptz-simulator/commit/0baedbd51e8112b332cf09362a33dcaddb944ccb))
* **skills:** address pelco-d review round two ([c0effe4](https://github.com/stritti/ptz-simulator/commit/c0effe48b186f3b821dbcedbdd13ae9084d5f57b))


### Documentation

* mention pelco-d in README transports and skills intro ([4ee73de](https://github.com/stritti/ptz-simulator/commit/4ee73de1ef360f3df4e69e9a3834cdc4b24b6278))

## [0.4.0](https://github.com/stritti/ptz-simulator/compare/v0.3.0...v0.4.0) (2026-11-07)


### Features

* **pelco-d:** simulate Pelco-D over a serial pseudo terminal ([3f45b8a](https://github.com/stritti/ptz-simulator/commit/3f45b8a72c377e37aa0b762533b6f2ec81b14a03))
* **skills:** add agent skills for conformant camera interfaces ([857b92e](https://github.com/stritti/ptz-simulator/commit/857b92e08d35ad486090ee87cf96a8d2c3da99ba))


### Bug Fixes

* **pelco-d:** correct preset, focus-near, speed and response encoding ([129ff42](https://github.com/stritti/ptz-simulator/commit/129ff425eaeb5348dd6e5e8fb60844564dbb6e13))
* **pelco-d:** resync splitter after invalid frames, honor --instant on recall ([9ce6a64](https://github.com/stritti/ptz-simulator/commit/9ce6a64ea5faab7d21e6b2bf5a61a4d4a1a65035))
* **skills:** address codex review findings ([f9a0baa](https://github.com/stritti/ptz-simulator/commit/f9a0baab32a241387c801ce1184f63f00d28a777))
* **skills:** address eighth codex review round ([510f650](https://github.com/stritti/ptz-simulator/commit/510f650be7a0c6e5bfdaed739e726868ab250c24))
* **skills:** address eleventh codex review round ([e253f34](https://github.com/stritti/ptz-simulator/commit/e253f3408ff3b688bf8f3bcd6df52917cfe971ee))
* **skills:** address fifth codex review round ([498e5d9](https://github.com/stritti/ptz-simulator/commit/498e5d9694316416b41d6fb40ddd136daabcc672))
* **skills:** address fourteenth codex review round ([52335cd](https://github.com/stritti/ptz-simulator/commit/52335cd9819d74fbfa7d4fa6f143b191dcc594ca))
* **skills:** address fourth codex review round ([58c77da](https://github.com/stritti/ptz-simulator/commit/58c77daa9aa6cb4a1e078448a475d1ed32b6a40f))
* **skills:** address ninth codex review round ([13696b3](https://github.com/stritti/ptz-simulator/commit/13696b34da3cb0ea40d17dc4f73b268167f037b0))
* **skills:** address second codex review round ([491387f](https://github.com/stritti/ptz-simulator/commit/491387f120a1000212a689bf78589b4c56bbd9f9))
* **skills:** address seventh codex review round ([7cba59e](https://github.com/stritti/ptz-simulator/commit/7cba59e62940617459c2c77350e46512c66fa19a))
* **skills:** address sixth codex review round ([bfe1d8f](https://github.com/stritti/ptz-simulator/commit/bfe1d8f7f4966fde8f27322a538d8ed7d928cae9))
* **skills:** address tenth codex review round ([7ebc402](https://github.com/stritti/ptz-simulator/commit/7ebc402bcc9294fcee07d1d33d3d9c29ae836988))
* **skills:** address third codex review round ([8e2dd5b](https://github.com/stritti/ptz-simulator/commit/8e2dd5b07f63447853d01205891402f4fe77ba95))
* **skills:** address thirteenth codex review round ([5f279f7](https://github.com/stritti/ptz-simulator/commit/5f279f76121b8506605fd859ee4bb2dd6c028d98))
* **skills:** address twelfth codex review round ([3259e7d](https://github.com/stritti/ptz-simulator/commit/3259e7deb1d97b57a1617dbca89762a83ba30297))


### Documentation

* list supported standards with versions and references ([58ee9a6](https://github.com/stritti/ptz-simulator/commit/58ee9a61a84e05125cb129b9d4e47544deb2fc97))
* make PyPI badge track new releases within minutes ([c3c3662](https://github.com/stritti/ptz-simulator/commit/c3c3662f00081d8e47d042e550c31abd7dbf87a2))
* state the implemented WS-Discovery version (1.0, 2005/04) ([19f78d4](https://github.com/stritti/ptz-simulator/commit/19f78d4808cca53a1fda1b565b8702da88c784af))
* **website:** add agent skills page to the documentation site ([3cdff2b](https://github.com/stritti/ptz-simulator/commit/3cdff2b7ac1fa14d556cb129f16116052356b4b1))
* **website:** document Pelco-D on the documentation site ([35177c5](https://github.com/stritti/ptz-simulator/commit/35177c50b64159986c0cf1abd3b611ab88e327fb))

## [0.3.0](https://github.com/stritti/ptz-simulator/compare/v0.2.0...v0.3.0) (2026-11-06)


### Features

* add protocol plugin interface for adding new protocols ([d2ecf5a](https://github.com/stritti/ptz-simulator/commit/d2ecf5a83bed20adc0e78dfcca24f00b7c797c62))
* **onvif:** add network health endpoint ([2c18e8d](https://github.com/stritti/ptz-simulator/commit/2c18e8d00bb7553bb4c825c8302ed0894d2423cf))
* **tui:** add landmarks to the simulated camera picture ([82c79e8](https://github.com/stritti/ptz-simulator/commit/82c79e8c2cdb386c717d51d3b7f420c084cc72e3))
* **tui:** add network-aware terminal dashboard ([cb74e86](https://github.com/stritti/ptz-simulator/commit/cb74e86a2bd48ce3566a1214cfedf3ffed0c1cbf))


### Bug Fixes

* **onvif:** protect health details without blocking camera control ([dc93aeb](https://github.com/stritti/ptz-simulator/commit/dc93aeb546f8a409a8b9e0de3ddb55aab0c5e3dd))
* release the serial pty and the NDI source when the simulator stops ([bb2e29e](https://github.com/stritti/ptz-simulator/commit/bb2e29e5e254ae68843704c83d48929ab965ffc8))
* stop a protocol plugin that fails during start-up ([2689a6e](https://github.com/stritti/ptz-simulator/commit/2689a6efbf653f0fae2b0e8d390fd782e7170095))
* **visca:** let a newer move supersede an older socket, keep cancel retransmit protected ([9f141a4](https://github.com/stritti/ptz-simulator/commit/9f141a479b22e96e48925cd278417c2af7141bfe))
* **visca:** two command sockets, IF_Clear, address set and 100 presets ([e350a2e](https://github.com/stritti/ptz-simulator/commit/e350a2e8f5544b79e64e668c34006096871131db))
* **visca:** two command sockets, IF_Clear, address set and 100 presets per Sony list ([e8fe66e](https://github.com/stritti/ptz-simulator/commit/e8fe66e78f5dc97cd82f621f40e07fbd79f436fd))


### Documentation

* add camera scene page with landmark images and coordinates ([a919846](https://github.com/stritti/ptz-simulator/commit/a91984624d7aa3d1c1b33cffb6de3a6d15158ab2))
* add status badges to README and website ([e6670b6](https://github.com/stritti/ptz-simulator/commit/e6670b66548ae6088fdac9ea2acc263ced52bdf8))
* link the protocol guide from README and AGENTS.md ([a050ece](https://github.com/stritti/ptz-simulator/commit/a050ece6f3ae426dbeb8cb8eceda7c6e487fddd2))
* **site:** add copyright and MIT license notice to footer ([fab9de1](https://github.com/stritti/ptz-simulator/commit/fab9de1e3764cdcec39be2609f7d27f1e82cc438))
* **website:** unify documentation under docs ([869e44a](https://github.com/stritti/ptz-simulator/commit/869e44ab6f0b1070e1380686cf19dc2e90dc38e8))

## [0.2.0](https://github.com/stritti/ptz-simulator/compare/v0.1.0...v0.2.0) (2026-11-06)


### Features

* interactive TUI with keyboard control ([a97b69f](https://github.com/stritti/ptz-simulator/commit/a97b69f9310e32a034460b6d015f4639c7fadc2c))
* **onvif:** --onvif-no-absolute simulates a camera without AbsoluteMove ([351890e](https://github.com/stritti/ptz-simulator/commit/351890e3b50a480591ed76a000f94bd9452420e9))
* **onvif:** Profile S basics and spec fixes (imaging dispatch, digest 401) ([56f57bf](https://github.com/stritti/ptz-simulator/commit/56f57bf8a1bd4f40250a2c046448301d9fc0f2b4))
* **onvif:** Profile S basics for media profile and device management ([e50918d](https://github.com/stritti/ptz-simulator/commit/e50918d43f65569a1c7ba68e0fc6f589afe06a50))
* PTZ camera simulator (ONVIF, VISCA, NDI) ([02fe1ff](https://github.com/stritti/ptz-simulator/commit/02fe1ffc07165d700701bea37858273fb9323421))
* **tui:** show the camera picture at the current position ([bd9ca2e](https://github.com/stritti/ptz-simulator/commit/bd9ca2e1287fcb6cbc6929c28bd221763b80ae7f))


### Bug Fixes

* **onvif:** enforce PTZ configuration removal and escape discovery scopes ([2c3dbc4](https://github.com/stritti/ptz-simulator/commit/2c3dbc4230a8af1a2787aea3ba8cc224be3c3fb7))
* **onvif:** follow ONVIF Core/PTZ spec 26.06 ([0fd4e52](https://github.com/stritti/ptz-simulator/commit/0fd4e522c0e261669b62d197a9ead5906862eea2))
* **onvif:** imaging dispatch, digest 401 and GetWsdlUrl per Core/Imaging spec ([169e915](https://github.com/stritti/ptz-simulator/commit/169e9159255db78354e97c89d1cc4f57644c1377))
* **visca,ndi:** follow the Sony VISCA-over-IP reference and the NDI SDK ([5985a96](https://github.com/stritti/ptz-simulator/commit/5985a96137b3fb0b036ee0e64af57eef04ec1b1c))


### Documentation

* add TUI screenshot to homepage ([76b9b34](https://github.com/stritti/ptz-simulator/commit/76b9b34c3e66061d814e6f56d5870dfe99eca9e1))
* add VitePress GitHub Pages site ([9b87461](https://github.com/stritti/ptz-simulator/commit/9b87461363b71779042e309f3a9830027a7e9c51))
* clarify hidden changelog types in AGENTS.md ([41795d4](https://github.com/stritti/ptz-simulator/commit/41795d444653ea8e64dd4150f26fc1e801281b4c))
* define Conventional Commits PR titles for Release Please ([8608d74](https://github.com/stritti/ptz-simulator/commit/8608d74ff380a6764efe0c27abaed35b22abdb07))
* define Conventional Commits PR titles for Release Please ([c65cf7c](https://github.com/stritti/ptz-simulator/commit/c65cf7c1d991b397c0beaf569790d139c5f975b5))
* generalize simulator documentation ([2ea35e0](https://github.com/stritti/ptz-simulator/commit/2ea35e00d474f38eed4ff349aa36a38abb2f7491))
