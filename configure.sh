#!/bin/sh
set -eu

# community is already enabled by alpine-make-vm-image defaults
apk add --no-cache sudo python3 openssh openrc xorg-server xf86-video-modesetting xf86-input-libinput mesa-dri-gallium mesa-egl xfce4 xterm xdotool font-dejavu firefox dbus dbus-x11 udev eudev xinit

# fixed 1024x768 display; GTK window resizes don't affect the framebuffer
install -d /etc/X11/xorg.conf.d
cat > /etc/X11/xorg.conf.d/10-size.conf <<'EOF'
Section "Device"
    Identifier "Default Device"
    Driver "modesetting"
EndSection
Section "Screen"
    Identifier "Default Screen"
    Device "Default Device"
    SubSection "Display"
        Virtual 1024 768
    EndSubSection
EndSection
EOF

# ad blocker: uBlock Origin Lite (MV3; full uBO is MV2 and won't load in Firefox 151)
install -d /usr/lib/firefox/distribution
wget -O /usr/lib/firefox/distribution/uBOLiteRedux.xpi \
	https://addons.mozilla.org/firefox/downloads/file/5044373/ublock_origin_lite-2026.920.1710.xpi
xpi_sum=$(sha256sum /usr/lib/firefox/distribution/uBOLiteRedux.xpi)
[ "${xpi_sum%% *}" = 'e963ebbefd12ae36d891393ff61940b8d94b605c2a8510d3749afff176d7ad7a' ] || {
	echo 'uBO Lite xpi sha256 mismatch' >&2
	exit 1
}
cat > /usr/lib/firefox/distribution/policies.json <<'EOF'
{
  "policies": {
    "ExtensionSettings": {
      "uBOLiteRedux@raymondhill.net": {
        "installation_mode": "force_installed",
        "install_url": "file:///usr/lib/firefox/distribution/uBOLiteRedux.xpi"
      }
    },
    "TranslateEnabled": false,
    "OverrideFirstRunPage": "",
    "OverridePostUpdatePage": "",
    "NewTabPage": false,
    "Homepage": {"URL": "about:blank", "Locked": true, "StartPage": "none"},
    "SearchSuggestEnabled": false,
    "NoDefaultBookmarks": true,
    "DontCheckDefaultBrowser": true,
    "DisableProfileImport": true,
    "DisableFirefoxAccounts": true,
    "OfferToSaveLoginsDefault": false,
    "DisableFirefoxStudies": true
  }
}
EOF

rc-update add udev sysinit
rc-update add udev-trigger sysinit
rc-update add udev-settle sysinit
rc-update add dbus
rc-update add sshd
rc-update add networking
rc-update add acpid

# login
adduser -D -s /bin/ash alpine
echo 'alpine:alpine' | chpasswd
echo 'root:alpine' | chpasswd
addgroup alpine input
addgroup alpine video
addgroup alpine audio
addgroup alpine netdev
echo 'alpine ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/alpine

# ssh access for openbot
install -d -m 700 -o alpine -g alpine /home/alpine/.ssh
install -m 600 -o alpine -g alpine /mnt/openbot_key.pub /home/alpine/.ssh/authorized_keys

cat > /etc/network/interfaces <<'EOF'
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet dhcp
    hostname openbot
EOF

echo openbot > /etc/hostname

install -d -o alpine -g alpine -m 0755 /home/alpine
cat > /home/alpine/.xinitrc <<'EOF'
exec startxfce4
EOF
chown alpine:alpine /home/alpine/.xinitrc
install -d -m 755 -o alpine -g alpine /home/alpine/.config
install -d -m 700 -o alpine -g alpine /home/alpine/.config/xfce4

# launch wrapper: detach GUI apps from the ssh session
cat > /usr/bin/launch <<'EOF'
#!/bin/sh
nohup "$@" >/dev/null 2>&1 &
EOF
chmod +x /usr/bin/launch

# ssh sessions get the GUI display
echo 'SetEnv DISPLAY=:0' >> /etc/ssh/sshd_config

# autologin + startx on tty1
cat > /bin/autologin <<'EOF'
#!/bin/sh
exec /bin/login -f alpine
EOF
chmod +x /bin/autologin
sed -i 's|^tty1::.*|tty1::respawn:/sbin/getty -n -l /bin/autologin 38400 tty1|' /etc/inittab
install -m 600 -o alpine -g alpine /dev/null /home/alpine/.Xauthority
echo '[ "$(tty)" = "/dev/tty1" ] && [ -z "$DISPLAY" ] && export DISPLAY=:0 XAUTHORITY=/home/alpine/.Xauthority && exec xinit /home/alpine/.xinitrc -- :0 vt1 -nolisten tcp' >> /home/alpine/.profile
