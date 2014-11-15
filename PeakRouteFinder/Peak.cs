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

        public override string ToString()
        {
            return(String.Format("{0}, {1}, {2}", name, lat, lon));
        }
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
