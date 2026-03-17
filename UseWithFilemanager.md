# Using FletCopy with File Managers

FletCopy accepts a source path as a command-line argument and an optional `-remove` flag to enable move mode.
This makes it easy to wire into any Linux file manager that supports custom right-click actions.

The general command pattern is:

```
python /path/to/main.py %f
python /path/to/main.py %f -remove
```

Replace `/path/to/main.py` with the actual path on your system.

---

## Thunar (XFCE)

Thunar has built-in support for custom actions via a graphical editor.

1. Open Thunar and go to **Edit → Configure Custom Actions**
2. Click the **+** button to add a new action
3. Fill in the fields:
   - **Name:** Copy with FletCopy
   - **Command:** `python /path/to/main.py %f`
4. Under the **Appearance Conditions** tab, check **Directories** (and **Other Files** if desired)
5. Click **OK**

For a move action, repeat the steps with `-remove` appended to the command and a different name.

Thunar also stores actions in `~/.config/Thunar/uca.xml` which can be edited directly.

---

## Nautilus (GNOME)

Nautilus uses executable scripts placed in a special directory. These appear under a **Scripts** submenu in the right-click menu.

Create the scripts directory if it does not exist:

```
mkdir -p ~/.local/share/nautilus/scripts
```

Create a file named `Copy with FletCopy` in that directory:

```bash
#!/bin/bash
python /path/to/main.py "$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS"
```

Make it executable:

```
chmod +x ~/.local/share/nautilus/scripts/Copy\ with\ FletCopy
```

The script appears under **Scripts** when you right-click a file or folder. Nautilus passes selected paths via the `NAUTILUS_SCRIPT_SELECTED_FILE_PATHS` environment variable.

---

## Nemo (Cinnamon)

Nemo supports custom actions via `.nemo_action` files placed in `~/.local/share/nemo/actions/`.

Create a file `fletcopy.nemo_action`:

```ini
[Nemo Action]
Name=Copy with FletCopy
Comment=Open selected path in FletCopy
Exec=python /path/to/main.py %F
Icon-Name=system-file-manager
Selection=any
Extensions=dir;
```

Nemo picks up the file automatically — no restart needed in most cases.

---

## Dolphin (KDE)

Dolphin uses Service Menus defined as `.desktop` files placed in `~/.local/share/kio/servicemenus/`.

Create a file `fletcopy.desktop`:

```ini
[Desktop Entry]
Type=Service
ServiceTypes=KonqPopupMenu/Plugin
MimeType=inode/directory;
Actions=fletcopy

[Desktop Action fletcopy]
Name=Copy with FletCopy
Exec=python /path/to/main.py %f
```

After placing the file, go to **Settings → Configure Dolphin → Services** to verify it appears, then restart Dolphin.

---

## Caja (MATE)

Caja supports both a graphical action editor (via the `caja-actions` extension) and a scripts folder.

For the scripts approach, place an executable script in `~/.config/caja/scripts/`:

```bash
#!/bin/bash
python /path/to/main.py "$CAJA_SCRIPT_SELECTED_FILE_PATHS"
```

Make it executable and it will appear under the **Scripts** submenu on right-click.

---

## PCManFM / PCManFM-Qt (LXDE / LXQt)

PCManFM uses `.desktop` files placed in `~/.local/share/file-manager/actions/`.

Create a file `fletcopy.desktop`:

```ini
[Desktop Entry]
Type=Action
Name=Copy with FletCopy
Profiles=profile-fletcopy;

[X-Action-Profile profile-fletcopy]
MimeTypes=inode/directory;
Exec=python /path/to/main.py %f
Name=Default profile
```

Restart PCManFM for the action to appear. For PCManFM-Qt, the same file format applies — restart from **LXQt Session Settings → Desktop**.

---

## Notes

- All file managers above pass the selected path in some form (`%f`, `%F`, or an environment variable). FletCopy only uses the first path argument, so single-selection is recommended.
- The `-remove` flag can be appended to any command to pre-enable move mode in the FletCopy UI.
- Paths with spaces should be handled by the shell automatically when using `%f` or the environment variable form.
