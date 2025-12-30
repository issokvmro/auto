import pytest
from pathlib import Path
from unittest.mock import Mock, patch
from rd_automator.torrent_creator import create_torrent
from rd_automator.rd_client import RealDebridClient

def test_create_torrent(tmp_path):
    # Create a dummy file
    source_file = tmp_path / "test_file.txt"
    source_file.write_text("Hello World content for torrenting.")
    
    output_dir = tmp_path / "output"
    
    torrent_path = create_torrent(
        source_path=source_file,
        output_path=output_dir,
        trackers=["udp://tracker.example.com:1337"]
    )
    
    assert torrent_path.exists()
    assert torrent_path.name == "test_file.txt.torrent"
    # Note: we are not parsing the torrent file back to verify contents 
    # to avoid extra dependencies in test, but existence is good first step.

@patch("rd_automator.rd_client.requests.request")
def test_rd_client_upload(mock_request, tmp_path):
    # Mock response
    mock_response = Mock()
    mock_response.json.return_value = {"id": "WAITING_FILE_SELECTION"}
    mock_response.raise_for_status.return_value = None
    mock_request.return_value = mock_response
    
    client = RealDebridClient(token="DUMMY_TOKEN")
    
    # Create a dummy torrent file to upload
    torrent_file = tmp_path / "test.torrent"
    torrent_file.write_text("dummy torrent content")
    
    torrent_id = client.upload_torrent(torrent_file)
    
    assert torrent_id == "WAITING_FILE_SELECTION"
    mock_request.assert_called_with(
        "PUT", 
        "https://api.real-debrid.com/rest/1.0/torrents/addTorrent", 
        headers={'Authorization': 'Bearer DUMMY_TOKEN'}, 
        data=match_file_structure
    )

def match_file_structure(arg):
    # Helper to check if file arg is correct structure
    )

@patch("rd_automator.seeder.subprocess")
def test_seeder_manager(mock_subprocess):
    from rd_automator.seeder import SeederManager
    
    # Mock popen
    mock_popen = Mock()
    mock_subprocess.Popen.return_value = mock_popen
    
    manager = SeederManager()
    
    # Mock exists check
    with patch("pathlib.Path.exists", return_value=True):
        seed_id = manager.start_seeding(Path("test.torrent"), Path("C:/downloads/source.mkv"))
        
    assert seed_id is not None
    assert seed_id in manager.processes
    
    # Check if correct args sent to popen
    args, _ = mock_subprocess.Popen.call_args
    cmd_list = args[0]
    assert "aria2c" in cmd_list
    assert "--seed-time=0" in cmd_list
    
    manager.stop_seeding(seed_id)
    mock_popen.terminate.assert_called_once()
    assert seed_id not in manager.processes
