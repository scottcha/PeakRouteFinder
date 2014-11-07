using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Device.Location;

namespace PeakRouteFinder
{
    public class Peak
    {
        public string name { get; set; }
        public double? lat { get; set; }
        public double? lon { get; set; }

        public GeoCoordinate geoCoordinate
        {
            get
            {
                if (lat != null && lon != null)
                {
                    return new GeoCoordinate(lat.Value, lon.Value);
                }
                else
                    return null;
            }
        }
    }
}
