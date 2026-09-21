alpine-virt-3.24.2-x86_64.iso:
	wget https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/alpine-virt-3.24.2-x86_64.iso

openbot.qcow2: alpine-virt-3.24.2-x86_64.iso
	sudo ./alpine-make-vm-image.sh \
		--branch v3.24 \
		--image-format qcow2 \
		--image-size 12G \
		--kernel-flavor virt \
		--serial-console \
		--packages "linux-virt" \
		--script-chroot \
		openbot.qcow2 \
		./configure.sh

run: openbot.qcow2
	sudo qemu-system-x86_64 \
		-machine q35,accel=kvm \
		-cpu host \
		-smp 2 \
		-m 3G \
		-drive file=openbot.qcow2,if=virtio,cache=writeback \
		-nic user,model=virtio-net-pci,hostfwd=tcp::2222-:22 \
		-device virtio-vga \
		-display gtk \
		-device virtio-tablet-pci

clean:
	rm -f openbot.qcow2
