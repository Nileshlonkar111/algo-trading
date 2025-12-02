#!/bin/bash

# Algo Trading Platform - Log Viewer Script
# This script provides easy access to application logs

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to display menu
show_menu() {
    echo -e "${GREEN}=========================================${NC}"
    echo -e "${GREEN}Algo Trading Platform - Log Viewer${NC}"
    echo -e "${GREEN}=========================================${NC}"
    echo ""
    echo "1. View real-time application logs (supervisor tail)"
    echo "2. View trade logs via API"
    echo "3. View notifications via API"
    echo "4. View today's gunicorn access logs"
    echo "5. Check application status"
    echo "6. View last 100 lines from supervisor"
    echo "7. Search logs for errors"
    echo "8. Export today's logs to file"
    echo "9. View all supervisor logs"
    echo "0. Exit"
    echo ""
}

# Function to get auth token
get_auth_token() {
    echo -e "${YELLOW}Enter admin password (default: admin123):${NC}"
    read -s password
    if [ -z "$password" ]; then
        password="admin123"
    fi
    
    response=$(curl -s -X POST http://localhost:8000/auth/login \
        -H "Content-Type: application/json" \
        -d "{\"username\":\"admin\",\"password\":\"$password\"}")
    
    token=$(echo $response | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)
    
    if [ -z "$token" ]; then
        echo -e "${RED}Authentication failed!${NC}"
        return 1
    fi
    echo "$token"
}

# Function to view real-time logs
view_realtime_logs() {
    echo -e "${BLUE}Viewing real-time logs (Press Ctrl+C to stop)...${NC}"
    sudo supervisorctl tail -f algo-trading
}

# Function to view trade logs
view_trade_logs() {
    token=$(get_auth_token)
    if [ $? -eq 0 ]; then
        echo -e "${BLUE}Fetching trade logs...${NC}"
        curl -s -H "Authorization: Bearer $token" http://localhost:8000/trades/logs | python3 -m json.tool
    fi
}

# Function to view notifications
view_notifications() {
    token=$(get_auth_token)
    if [ $? -eq 0 ]; then
        echo -e "${BLUE}Fetching notifications...${NC}"
        curl -s -H "Authorization: Bearer $token" http://localhost:8000/notifications?limit=100 | python3 -m json.tool
    fi
}

# Function to view today's logs
view_today_logs() {
    echo -e "${BLUE}Fetching today's logs from supervisor...${NC}"
    sudo supervisorctl tail -1000 algo-trading | grep "$(date '+%Y-%m-%d')" || echo "No logs found for today"
}

# Function to check status
check_status() {
    echo -e "${BLUE}Application Status:${NC}"
    echo "===================="
    sudo supervisorctl status algo-trading
    echo ""
    echo -e "${BLUE}Health Check:${NC}"
    curl -s http://localhost:8000/health | python3 -m json.tool
    echo ""
    echo -e "${BLUE}Running Processes:${NC}"
    ps aux | grep gunicorn | grep -v grep
}

# Function to view last 100 lines
view_last_100() {
    echo -e "${BLUE}Last 100 log entries:${NC}"
    sudo supervisorctl tail -100 algo-trading
}

# Function to search for errors
search_errors() {
    echo -e "${BLUE}Searching for errors...${NC}"
    sudo supervisorctl tail -1000 algo-trading | grep -i "error\|err\|failed\|exception" || echo "No errors found"
}

# Function to export logs
export_logs() {
    filename="trading_logs_$(date '+%Y%m%d_%H%M%S').txt"
    echo -e "${BLUE}Exporting logs to ~/$filename${NC}"
    sudo supervisorctl tail -10000 algo-trading > ~/$filename
    echo -e "${GREEN}Logs exported to ~/$filename${NC}"
}

# Function to view all supervisor logs
view_all_supervisor_logs() {
    echo -e "${BLUE}All supervisor logs (last 500 lines):${NC}"
    sudo supervisorctl tail -500 algo-trading
}

# Main loop
while true; do
    show_menu
    read -p "Enter your choice: " choice
    echo ""
    
    case $choice in
        1) view_realtime_logs ;;
        2) view_trade_logs ;;
        3) view_notifications ;;
        4) view_today_logs ;;
        5) check_status ;;
        6) view_last_100 ;;
        7) search_errors ;;
        8) export_logs ;;
        9) view_all_supervisor_logs ;;
        0) 
            echo -e "${GREEN}Goodbye!${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid option. Please try again.${NC}"
            ;;
    esac
    
    echo ""
    read -p "Press Enter to continue..."
    clear
done