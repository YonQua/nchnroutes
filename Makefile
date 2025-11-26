produce:
	git pull
	curl -o ipv4-address-space.csv https://www.iana.org/assignments/ipv4-address-space/ipv4-address-space.csv
	curl -o cn_ipv4_list.txt https://cdn.leishao.nyc.mn/http://www.iwik.org/ipcountry/mikrotik/CN
	curl -o cn_ipv6_list.txt https://cdn.leishao.nyc.mn/http://www.iwik.org/ipcountry/mikrotik_ipv6/CN
	python3 produce.py
	sudo mv routes4.conf /etc/bird/routes4.conf
	sudo mv routes6.conf /etc/bird/routes6.conf
	sudo birdc configure
