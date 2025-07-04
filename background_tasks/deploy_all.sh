#!/bin/bash
cd parse_html_to_csv && bash ./deploy.sh && cd ..
cd load_csv_to_db && bash ./deploy.sh && cd .. 