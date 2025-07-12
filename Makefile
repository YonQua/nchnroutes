produce:
	git pull
	curl -o delegated-apnic-latest https://ftp.apnic.net/stats/apnic/delegated-apnic-latest
	curl -o cn_ipv4_list.txt http://www.iwik.org/ipcountry/mikrotik/CN
	curl -o cn_ipv6_list.txt http://www.iwik.org/ipcountry/mikrotik_ipv6/CN
	python3 produce.py
	sudo mv routes4.conf /etc/bird/routes4.conf
	sudo mv routes6.conf /etc/bird/routes6.conf
	sudo birdc configure
