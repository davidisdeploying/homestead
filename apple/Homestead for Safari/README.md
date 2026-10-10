# Homestead for Safari

Native iOS/iPadOS and macOS containers for the canonical WebExtension in
`../../../extension`.

- App ID: `cc.davidgomez.homestead.safari`
- Extension ID: `cc.davidgomez.homestead.safari.Extension`
- The same pair is used on iOS/iPadOS and macOS.
- `Shared (Extension)/Resources` is a relative symlink to the repository's
  canonical `extension/` directory. Do not copy or fork those resources.

The wrapper adds no credential store, background collection, service token, or
alternate ingress. Listing extraction remains user initiated, previewed, and
explicitly saved through the existing Homestead origin.

Build without signing:

```sh
xcodebuild -project 'apple/Homestead for Safari/Homestead for Safari.xcodeproj' \
  -scheme 'Homestead for Safari (iOS)' -sdk iphonesimulator \
  CODE_SIGNING_ALLOWED=NO build
xcodebuild -project 'apple/Homestead for Safari/Homestead for Safari.xcodeproj' \
  -scheme 'Homestead for Safari (macOS)' -sdk macosx \
  CODE_SIGNING_ALLOWED=NO build
```
