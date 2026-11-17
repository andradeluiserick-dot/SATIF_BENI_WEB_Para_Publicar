import io
import sys
import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import query_firms_period, fetch_weather, parse_hotspots, group_hotspots_grid

class FakeResponse:
    status_code=200
    text='latitude,longitude,acq_date,acq_time,frp,satellite\n-13.6,-65.1,2026-11-15,0530,10.1,N21\n'
    def raise_for_status(self): pass
    def json(self):
        return {'current':{'temperature_2m':31,'relative_humidity_2m':29,'wind_speed_10m':32,'time':'2026-11-17T10:00'},'hourly':{}}

class V2Tests(unittest.TestCase):
    def test_nasa_url_historical_and_validate(self):
        today=date.today()-timedelta(days=2)
        with patch('core.requests.get',return_value=FakeResponse()) as request:
            result=query_firms_period('FAKEKEY123456','VIIRS_NOAA21_NRT',today.isoformat(),2)
            self.assertEqual(len(result),1)
            self.assertEqual(result.iloc[0]['producto'],'VIIRS_NOAA21_NRT')
            self.assertIn(f'/2/{today.isoformat()}',request.call_args.args[0])
            self.assertIn('SATIF-Beni-Web/2.0',request.call_args.kwargs['headers']['User-Agent'])

    def test_bad_query_no_request(self):
        with patch('core.requests.get') as req:
            with self.assertRaises(ValueError):
                query_firms_period('FAKEKEY123456','VIIRS_NOAA21_NRT','2099-01-01',1)
            req.assert_not_called()

    def test_private_key_never_in_exception(self):
        import requests
        secret='FAKEKEY123456'
        with patch('core.requests.get',side_effect=requests.exceptions.ConnectionError('Error on /'+secret)):
            with self.assertRaises(ValueError) as ctx:
                query_firms_period(secret,'VIIRS_NOAA21_NRT','2026-11-10',1)
            self.assertNotIn(secret,str(ctx.exception))

    def test_weather(self):
        with patch('core.requests.get',return_value=FakeResponse()) as req:
            result=fetch_weather(-13.67,-65.32)
            self.assertEqual(result['current']['temperature_2m'],31)
            self.assertEqual(req.call_args.kwargs['params']['timezone'],'America/La_Paz')

    def test_grid_grouping(self):
        df=parse_hotspots(io.StringIO('latitude,longitude,acq_date,acq_time,frp,satellite\n-13.6,-65.1,2026-11-15,0530,10,N21\n-13.602,-65.104,2026-11-15,0540,20,N21\n'))
        df['municipio']='Guayaramerín'
        grids=group_hotspots_grid(df,10)
        self.assertEqual(grids.detecciones.sum(),2)
        self.assertGreaterEqual(grids.detecciones.max(),1)

if __name__=='__main__': unittest.main()
