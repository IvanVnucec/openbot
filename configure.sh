#!/bin/sh
set -eu

# community is already enabled by alpine-make-vm-image defaults
apk add --no-cache sudo openssh openrc xorg-server xf86-video-qxl xf86-video-modesetting xf86-input-libinput mesa-dri-gallium mesa-egl xfce4 xterm font-dejavu firefox dbus dbus-x11 udev eudev xinit

setup-udev || true
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
echo '[ "$(tty)" = "/dev/tty1" ] && [ -z "$DISPLAY" ] && exec startx' >> /home/alpine/.profile
