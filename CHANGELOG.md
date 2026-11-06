# Changelog

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
