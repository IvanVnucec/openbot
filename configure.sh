#!/bin/sh
set -eu

# community is already enabled by alpine-make-vm-image defaults
apk add --no-cache sudo openssh openrc xorg-server xf86-video-qxl xf86-video-modesetting xf86-input-libinput mesa-dri-gallium mesa-egl openbox xterm font-dejavu firefox dbus dbus-x11 udev eudev xinit

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
    hostname ffbox
EOF

echo ffbox > /etc/hostname

install -d -o alpine -g alpine -m 0755 /home/alpine
cat > /home/alpine/.xinitrc <<'EOF'
firefox &
exec openbox-session
EOF
chown alpine:alpine /home/alpine/.xinitrc

# console hint
echo 'Type: startx' > /etc/motd
