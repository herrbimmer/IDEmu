# iDrive Touch Controller (iDrive 5/6, NBT Evo)

The iDrive 5/6 controller has a touchpad on top of the knob. IDEmu emulates it from the web UI: the controller card of the run screen
has an **iDrive Touch Controller** pad. Drawing on it reaches the HMI the way the real touchpad does, so the screens that use the
touchpad respond to it: handwriting in the address and search spellers, and CarPlay (the HMI passes the touchpad on as
`CarPlayTouchPadInput` while CarPlay has focus; bringing CarPlay up in IDEmu is separate work).

## Using it

The pad is shown only when the environment's coding has the touch controller: `ZBE_TOUCH` = 1 (IDEmu codes it for every iDrive 5/6
head unit except EntryNav; it can be changed in the coding editor). Without it the API answers 409.

* **One finger:** press and drag on the pad. While one finger is down the strokes stay on the pad as ink (cleared 1.2 s after the last
  one).
* **Two fingers**, as in the iOS Simulator: hold **Alt** or **Ctrl** when touching and a second finger is mirrored around the centre
  (pinch / spread). Add **Shift** (also during a drag) to keep the distance between the two and move both together; releasing Shift goes
  back to the mirror. Hovering with Alt/Ctrl shows where the two fingers would land.
* **Handwriting:** in a speller (e.g. the POI keyword search) write one character at a time with one finger. 0.7 s after the last
  stroke IDEmu reads it and the HMI enters it, as with the real controller. Needs `bin/hwr`: build it once with `tools/hwr/build.sh`
  (macOS 14+, uses the system's Vision framework).
* API: `POST /api/input/touchpad {x, y, down, move, x2, y2}`. `x`, `y` from 0 to 1 (top left = 0, 0); `down: true` touches,
  `move: true` moves, `down: false` lifts; `x2`, `y2` add a second finger. iDrive 5/6 only (501 on other generations).

Outside screens that switch the touchpad on, the HMI drops these touches (`TP blocked` in the HMI log), as in the car.

## How it works

### The touchpad path
Read from HMI 006_017_006 (`CTouchPadService`, `CCarPlayActivity::handleTouchInput`) and run in IDEmu:

```
controller --MOST 0xE5.01 CccsGestureRecognition 0xC43 (gesture start)--+
           --MOST 0xE5.01 CccsAbsoluteCoordinates 0xC44 (coordinates)--+--> CTouchPadService --CTouchData origin 3--> CTouchDataClient
--> CCarPlayActivity::handleTouchInput ("Touched Touchpad") --MOST 0x24.70 CarPlayTouchPadInput 0xCD4--> Connectivity (CarPlay)
```

* **When it is on.** `CCarPlayActivity` starts the touchpad on focus: `TP start mode 2 (NotUsed)`, `TP switchTouchPad true OP:2
  TA:0x1100`, `TouchDataClient1 TP unblocked`. Mode 2 is gesture mode: the controller recognises the gesture itself. The touchpad is
  off again when CarPlay loses focus.
* **`CccsAbsoluteCoordinates` 0xC44 Status (13 bytes):** u8 counter, then two fingers of {u16 x, u16 y (0..0xFFF, 0xFFF = none),
  u8 (0 = touching, 1..14 = lifted, 15 = none), u8 state (0..3)}. The HMI scales to 0..511 (`x >> 3`, `(0xFFE - y) >> 3`).
* **`CccsGestureRecognition` 0xC43 Status (11 bytes):** u8 gesture (1 tap, 2 LONGPRESS, 4 SWIPE, 5 SPREAD, 6 PINCH, 7 SCROLL,
  8 DOUBLETAP, 9 ROTATE), u16 x, u16 y, then six small fields not fully decoded. In gesture mode the coordinates only become touches
  while a recognised gesture is queued. **Wrong values here crash the HMI**, so IDEmu does not emulate the controller at this level.
* **`CarPlayTouchPadInput` 0xCD4 (HMI -> CarPlay):** u8 count, then per finger u16 x, u16 y (0..511), u8 z (50), u8 state
  (0 down, 1 move, 2 up). The touch's finger id is the index: a second, empty finger with the same id overwrites the first.

**In IDEmu** the shim delivers the touches one step later, where `CTouchPadService` would: a `CTouchData` with origin 3, coordinates
0..511, z 50, finger ids 0 and 1, without the touchscreen fix-ups (origin 1 enable, display wake-up, gestures). Guest input events
(`src/shim/hook.c`): **41** = state, `x | y << 16`, time (bit 0x100 in the state = with a second finger), preceded by **42** = state and
position of the second finger. `CCarPlayActivity` turns them into `CarPlayTouchPadInput` with one or two fingers (verified:
`pad 02 00cc 00cc 32 00 0133 0133 32 00  204,204 down; 307,307 down`, with a fake iPhone connected over the virtual MOST bus).

Whether a real iPhone would use it depends on Connectivity declaring a touchpad to the phone (`[TouchPadInput]` in `carplay.ini`); the
stock MINI configuration does not. Untested in the car.

### Handwriting
In the car the touch controller recognises the character itself; the HMI only receives the candidates. Read from HMI 006_017_006
(`CTouchPadService::onStatusCCSFktIDs`, `onCCSCharacterRecognitionStatus`):

* **FktIDs decide the function.** The HMI asks 0xE5.01 for its FktIDs (function 0x000 Get) and uses `CccsCharacterRecognition2`
  0xC45 if listed, else `CccsCharacterRecognition` 0xC42 (`TP (@1) set CharRecogFctID C45`), and only then subscribes to it. The
  FktIDs list is read as 12-bit pairs; a function below the first value counts as listed, so `FF FF FF` lists all of them. Without an
  answer handwriting never reaches the HMI.
* **The speller switches it on:** `TP start mode 1 (C45)` and `CccsTouchControl` 0xC41 Set to the controller, e.g.
  `03 0F 02 00 00 00 00 01`: byte 1 = character classes (1 digits, 2 upper case, 4 lower case, 8 special), byte 2 = language.
  CarPlay sends `.. 00 FF .. BF ..` (gestures only), and `.. 00 FF 00 ..` switches it off.
* **`CccsCharacterRecognition(2)` Status:** u8 number of candidates, then two candidates {u8 id, u8 probability %, u16 character
  (UTF-16)}, and for 0xC45 one more u8. More candidates come in further messages (ids 2-3, ...). The HMI re-ranks them for the
  speller (`TP prioritized recognized character 'M' by +15%`) and enters the best one (`SPELLER: spellerCharSelected; char="M";
  fromtouch=1`). It is ignored while recognition is off or the "touchpad speller" setting is off.

**In IDEmu** `idemu/most.py` answers the controller's FktIDs (and sends them once unasked, for an HMI restored from a snapshot that
asked before the bridge existed) and remembers the last `CccsTouchControl`. While it asks for characters, the strokes drawn on the
pad are collected (`idemu/hwr.py`); 0.7 s after the last one `bin/hwr` (`tools/hwr/hwr.m`, macOS Vision text recognition) reads
them, and the candidates (Cyrillic/Greek look-alikes mapped to Latin, the other case and confusable characters added, filtered by the
classes the HMI wants) go to the HMI as 0xC45. Verified in the POI keyword speller: writing M then A gave `MA`. The address input's
country entry does not open in IDEmu (no map database), so the address spellers themselves are untested here.

## Limits

* No gesture emulation at the `CccsGestureRecognition` level (see above): screens that only react to recognised controller gestures
  (e.g. map pinch through the controller) do not get them.
* Handwriting needs macOS (Vision); on other hosts `bin/hwr` is missing and the strokes are only passed on as touches.
