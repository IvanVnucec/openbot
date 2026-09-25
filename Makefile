all: setup

setup: openbot.qcow2

openbot_key:
	ssh-keygen -t ed25519 -f openbot_key -N '' -C openbot

apk-cache:
	mkdir -p apk-cache

openbot.qcow2: openbot_key apk-cache
	sudo env APK_CACHE_DIR=$(CURDIR)/apk-cache APK_OPTS="--no-progress --cache-packages" ./alpine-make-vm-image.sh \
		--branch v3.24 \
		--image-format qcow2 \
		--image-size 12G \
		--kernel-flavor virt \
		--serial-console \
		--packages "linux-virt" \
		--script-chroot \
		openbot.qcow2 \
		./configure_vm.sh
	sudo chown $(USER) openbot.qcow2

boot: openbot.qcow2
	qemu-system-x86_64 \
		-machine q35,accel=kvm \
		-cpu host \
		-smp 2 \
		-m 3G \
		-drive file=openbot.qcow2,if=virtio,cache=writeback \
		-nic user,model=virtio-net-pci,hostfwd=tcp::2222-:22 \
		-device virtio-vga \
		-display gtk \
		-device virtio-tablet-pci \
		-qmp unix:/tmp/openbot-qmp.sock,server,nowait

clean:
	rm -f openbot.qcow2 openbot_key openbot_key.pub
